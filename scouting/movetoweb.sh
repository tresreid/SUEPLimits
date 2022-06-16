#!/bin/bash

dir=${PWD}/Plots
#dir=${PWD}/Displays
for d in $(find ${dir} -type d)
do
  #Do something, the directory is accessible with $d:
  echo $d
  python3 $dir/../make_html_listing.py $d
done
#outdir=/publicweb/m/mreid/SUEPs/trackStudy_ptErr
outdir=/publicweb/m/mreid/SUEPs/ABCD
#outdir=/publicweb/m/mreid/SUEPs/ProductionTestNewV1
rm -r $outdir
mkdir $outdir
cp -r $dir/* $outdir

