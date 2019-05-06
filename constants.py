### Bitcoin ###
BLOCK_CAPACITY_WU         = 4 * 1000 * 1000
TARGET_BLOCK_TIME_MINUTES = 10

# Satoshis in one BTC
COIN = 100 * 1000 * 1000  
######



### Estimation configuration ###

# Flow sampling multipler 
# example: with 2 => To compute estimations for 1h, will sample over the last 2h of transactions
FLOW_TIMESPAN_MULTIPLIER = 2 

MIN_FEE_RATE = 1
MAX_FEE_RATE = 10000


# All probabilites for which we're going to compute estimates.
# In a nutshell, these correspond to block luckiness.
# The higher the number, the more the estimator is going to assume
# the next blocks will be unlucky (raising fees to compensate).
TARGETS_CONFIDENCE = [.5, .8, .9]

# Confirmation windows to compute estimates for
TARGETS_MINUTE = [30, 60, 60*2, 60*3, 60*6, 60*12, 60*24]

######
