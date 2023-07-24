#!/bin/bash -e
#
#
# Verilator v5.012+ (maybe v5.006+ works, but older is known to have incompatible VPI issues)
# cocotb 0.9.0-dev
# lcov 1.14+
#
# make clean
# SIM=verilator COVERAGE=yes make
# ./converage.sh verilator
#
SIM="$1"

if [ "$SIM" = "verilator" ]
then
	rm -rf coverage_html_old
	test -d coverage_html && mv coverage_html coverage_html_old
	test -d coverage_html || mkdir coverage_html

	# It is possible to run multiple test runs with separate coverage data
	# Then collate and merge the data and report
	covfiles=$(find . -maxdepth 1 -type f -name "*.dat" -not -name final.dat)
	verilator_coverage -write final.dat -write-info final.info $covfiles

	lcov -l final.info

	genhtml --output-directory coverage_html final.info

	lcov --summary final.info

fi

if [ -n "$GITHUB_STEP_SUMMARY" ] && [ -f final.info ]
then
	(
		echo "### $SIM Coverage Report"
		echo ""
		lcov -l final.info | tail -n +2 | egrep -v "^\[/"
		echo ""
	) >> $GITHUB_STEP_SUMMARY
fi
