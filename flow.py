# Calculations and estimations of fees

import scipy
import scipy.stats

import constants

POSITIVE_INFINITY = float('inf')
NAN = float('NaN')



class FeeBuckets:
    """ Versatile class to store numerical data associated to different fee levels.
    """

    def __init__(self):
        # TODO: use an array rather than a dict, to improve performance

        # Maps fee_rate => WU
        self._buckets = {}

    def _normalize(fee_rate):
        fee_rate = min(fee_rate, constants.MAX_FEE_RATE)
        fee_rate = max(fee_rate, constants.MIN_FEE_RATE)

        return fee_rate

    
    def divide(self, factor):
        """ Divides all bucket's values by a factor """
        for k in self._buckets:
            self._buckets[k] /= factor

    
    def clone(self):
        o = FeeBuckets()
        o._buckets = self._buckets.copy()
        return o

    
    def sum(self):
        """Returns the sum of all bucket's values."""

        value = 0

        for k in self._buckets:
            value += self._buckets[k]

        return value

    
    def get_aggregate_sup(self, threshold):
        """ Returns the sum of all bucket's values whose fee rate is greater than
            or equal to *threshold*
        """

        value = 0
        for k in self._buckets:
            if k >= threshold:
                value += self._buckets[k]

        return value

    
    def max_fee_rate(self):
        """Returns the maximum fee rate with a non-zero value"""

        keys = self._buckets.keys()
        if len(keys) == 0:
            return 0

        return max(keys)

    def add(self, other):
        """ Given another FeeBuckets object, add all of its values
            to our own values.
        """

        for k in other._buckets:
            self[k] += other[k]

    def descending_keys(self):
        """ Returns a list of all of our non-zero fee rates in descending order. """
        keys = list(self._buckets.keys())
        keys.sort(reverse=True)
        return keys

    def ascending_keys(self):
        """ Returns a list of all of our non-zero fee rates in ascending order. """
        keys = list(self._buckets.keys())
        keys.sort()
        return keys

    def __contains__(self, fee_rate):
        fee_rate = FeeBuckets._normalize(fee_rate)
        return fee_rate in self._buckets and self._buckets[fee_rate] > 0

    def __str__(self):
        keys = list(self._buckets.keys())
        keys.sort()
        return ', '.join([str(k) + "=" + str(self[k]) for k in keys])

    def __getitem__(self, fee_rate):
        fee_rate = FeeBuckets._normalize(fee_rate)

        if fee_rate in self._buckets: 
            return self._buckets[fee_rate]
        else:
            return 0

    def __setitem__(self, fee_rate, value):
        fee_rate = FeeBuckets._normalize(fee_rate)

        if value == 0:
            del self._buckets[fee_rate]
        else:
            self._buckets[fee_rate] = value  




def to_fee_rate(satoshis, weight):
    """ Computes a fee rate given a total fee in satoshis and a weight.
        Outputs in sats/vbyte.
        Sats/vbyte are used instead of sats/WU in order to provide more granularity
    """

    return int(4 * satoshis / weight) 

def get_prob_of_min_blocks(minutes, blocks):
    """ Returns the probability of finding more than *blocks* blocks. """
    expected = minutes / constants.TARGET_BLOCK_TIME_MINUTES
    return 1 - scipy.stats.poisson(expected).cdf(blocks)

def get_min_expected_blocks(minutes, target_prob):
    """ Returns the minimum number of blocks we can expect after *minutes*
        with *target_prob* probability.
    """

    blocks = 0

    while True:
        prob = get_prob_of_min_blocks(minutes, blocks)

        if prob < target_prob:
            break
    
        blocks+= 1

    return blocks

def compute_bucket(minutes, confidence, start_weight, weight_incr_rate_per_min):
    """ Simulates the lifecycle of a bucket using the following parameters:

        minutes                  -- Number of minutes to simulate (float)
        confidence               -- The selected probability to determine how many blocks to expect (float)
        start_weight             -- WU in the bucket at the start of the simulation
        weight_incr_rate_per_min -- WU being added to the bucket every minute.

        Returns True if the bucket became empty, False if it's still full.
    """

    # Maximum WU decrease per block = block capacity
    decr_weight_per_drain_event = constants.BLOCK_CAPACITY_WU

    weight_gain_over_interval = weight_incr_rate_per_min * minutes 

    min_expected_drain_events = get_min_expected_blocks(minutes, confidence)
    weight_lost_over_interval = decr_weight_per_drain_event * min_expected_drain_events

    weight_delta_over_interval = weight_gain_over_interval - weight_lost_over_interval

    end_weight = start_weight + weight_delta_over_interval

    return end_weight <= 0



def correction_decreasing_fees(estimates, list_windows, list_confidence):
    """ Enforces decreasing fees as the confirmation window gets longer.

        estimates       -- nested dict: delay -> confidence -> fee rate
        list_windows    -- list of confirmation windows (in minutes or blocks, doesn't matter)
        list_confidence -- list of confidence value
    """

    for confidence in list_confidence:
        min_value = POSITIVE_INFINITY
        for delay in list_windows:
            value = estimates[delay][confidence]
            min_value = min(min_value, value)
            estimates[delay][confidence] = min_value


def compute_estimates_by_minute(mempool, flow, targets_minute):
    """ Computes estimates by minute. 
        Same arguments as in *compute_estimates()*.
    """

    # Compute the max non-zero fee-rate across all flows and the mempool
    max_fee_rate_in_flow = max(map(lambda x: flow[x].max_fee_rate(), flow))
    max_fee_rate = max(mempool.max_fee_rate(), max_fee_rate_in_flow )
    
    # Nested dicts
    # minute -> confidence -> fee_rate
    output = {}

    for minutes in targets_minute:
        output[minutes] = {}
        for confidence in constants.TARGETS_CONFIDENCE:
            min_fee_rate_that_works = POSITIVE_INFINITY
            
            # Iterate through all fee rates,
            # run outcome simulations,
            # then stop once we find one that empties the bucket.
            for fee_rate in range(1, max_fee_rate+2):
                result = compute_bucket(
                    minutes, 
                    confidence, 
                    mempool.get_aggregate_sup(fee_rate), 
                    flow[minutes].get_aggregate_sup(fee_rate)) 

                if result:
                    min_fee_rate_that_works = min(min_fee_rate_that_works, fee_rate)
                    break

            output[minutes][confidence] = min_fee_rate_that_works

    # Enforce decreasing fees as the confirmation window gets larger
    correction_decreasing_fees(output, targets_minute, constants.TARGETS_CONFIDENCE)

    return output

def compute_estimates(mempool, flow, targets_minute):
    """ Main method to compute all estimates given the following parameters:

        mempool -- FeeBuckets that contain the WU currently in the mempool.
        flow    -- dict of *minutes*->FeeBuckets that contain the WU/min speed currently increasing the mempool.
                   The key serves to differentiate the different flows that will be used for each target minute,
                   it must match the elements in *targets_minute*.
        targets_minute -- list of delays in minutes to compute estimates for ([30, 60, ...])

        Returns nested dictionaries that can be navigated as such:
        output["by_minute"][*delay in minutes*][*confidence*] = fee_rate

        *NOT IMPLEMENTED!*
        output["by_block"][*max delay in blocks*][*confidence*] = fee_rate
    """
    return {
        "by_minute": compute_estimates_by_minute(mempool, flow, targets_minute),
        "by_block": {"1": {"0.5": NAN, "0.8": NAN, "0.9": NAN}} # TODO
    }
