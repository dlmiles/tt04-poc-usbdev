#!/bin/bash -e
#
# A script to encapsulate the steps to perform project specific coverage generation.
# Multiple coverage runs are possible and can be aggregated for reporting purposes.
# See also the GHA custom action in the coverage directory for other parts of the action.
#
# Verilator v5.012+ (maybe v5.006+ works, but older is known to have incompatible VPI issues)
# cocotb 0.9.0-dev
# lcov 1.14+
#
# make clean
# SIM=verilator COVERAGE=yes make
# ./coverage.sh verilator
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
		_GITHUB_PROJECTNAME=$(echo -n "$GITHUB_REPOSITORY" | sed -e 's#.*/##')
		echo "## $SIM Coverage Report [link](https://${GITHUB_REPOSITORY_OWNER}.github.io/${_GITHUB_PROJECTNAME}/coverage/)"
		echo ""
		lcov -l final.info | ./coverage.pl
		echo ""
		echo "-----"
		echo ""
		echo "| Tool        | Version |"
		echo "| :---        | :---    |"
		echo "| Verilator   | $(verilator --version) |"
		echo "| cocotb      | $(cocotb-config --version) |"
	) >> $GITHUB_STEP_SUMMARY
fi
