# Script Runner test script
cmd("GATE EXAMPLE")
wait_check("GATE STATUS BOOL == 'FALSE'", 5)
