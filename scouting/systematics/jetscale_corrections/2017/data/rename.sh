#!/bin/bash
for file in *.txt; do 
    mv -- "$file" "${file%.txt}.jec.txt"
done
