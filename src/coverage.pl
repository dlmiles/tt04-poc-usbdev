#!/usr/bin/perl
#
# The purpose of this Perl script is to reformat the standard output text from lcov
# into a pretty form github can render in the HTML action output.
#
# lcov -l final.info | ./coverage.pl
#
use strict;
use warnings;



my($emit_justify) = 0;

while(<>) {
    chomp;

    if($. < 2 && /^Reading/) {
        next;	# omit
    }

    if(/^===={10,}$/) {
        if(!$emit_justify) {
            print "| :----                                     |   ---: |  ---: |   ---: |  ---: |   ---: |  ---: |\n";
            $emit_justify = 1;
        }
        next;	# omit
    }
    if(/^\[\//) {
        next;	# omit
    }
    if(/\|\s*Lines\s*\|\s*Functions\s*/i) {
        next;	# omit
    }

    if(/^|/) {
        $_ = '| ' . $_;
    }
    if(/[^|](\s?)$/) {
        my $spc = $1;
        $_ = $_ . $spc . '|';
    }

    s/Rate\s+Num/   Rate |   Num /g;
    s/\s*([\d\.]+%)\s+(\d+)\s*/ $1 | $2 /g;
    s/\s*([\-])\s+(\d+)\s*/ $1 | $2 /g;

    print $_, "\n";
}

