#!/system/bin/sh
B=/data/local/tmp/ap/bin; P=/data/local/tmp/ap/pair; M=$1
export LD_LIBRARY_PATH=$B
$B/liblt_proc.so -w $P/$M.automorf.bin | $B/libcg_proc.so -w $P/$M.rlx.bin | $B/libapertium_tagger.so -g $P/$M.prob | $B/libapertium_pretransfer.so | $B/liblt_proc.so -b $P/$M.autobil.bin | $B/liblrx_proc.so -m $P/$M.autolex.bin | $B/libapertium_transfer.so -b $P/apertium-srd-ita.$M.t1x $P/$M.t1x.bin | $B/libapertium_interchunk.so $P/apertium-srd-ita.$M.t2x $P/$M.t2x.bin | $B/libapertium_postchunk.so $P/apertium-srd-ita.$M.t3x $P/$M.t3x.bin | $B/liblt_proc.so -g $P/$M.autogen.bin | $B/liblt_proc.so -p $P/$M.autopgen.bin
