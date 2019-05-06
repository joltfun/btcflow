#!/bin/bash
if [ "$FLOW_MODE" == "LOG" ]; then
    echo "Mode: log"
    exec python main_txlogger.py 
elif [ "$FLOW_MODE" == "COMPUTE" ]; then
    echo "Mode: compute"
    exec sh compute_loop.sh
fi
