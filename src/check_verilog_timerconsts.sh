#!/bin/bash
#
# The purpose of this script is to provide a check/validation/change of the
# timer constant values hardwired into the verilog are setup for.
#
# These constants need to be a specific value in production for the 48MHz
# PHY clock.  These values are too large for everyday simulation and testing
# so reduced figure is used to speed up development simulation.
#
# The LOW_SPEED 1/20 represents the fastest speed up possible that will not
# trigger timer event conditions with any of the test cases.
#
# If you are only performing FULL_SPEED testing (not LOW_SPEED) then you can
# use the 1/200 mode for even faster speedup of resets.  But at this speedup
# you cannot test LOW_SPEED.
#
#
# If you just run this utility it will report the current mode encoded into
# the verilog and provide a non-zero exit status if that is not the production
# values.
#
#
VERILOG_FILE="UsbDeviceTop.v"

ask="PROD"
patch=0
verbose=1
while [ $# -gt 0 ]
do
	case "$1" in
	fs|FS|-fs|-FS)
		ask="FS"
		;;
	ls|LS|-ls|-LS)
		ask="LS"
		;;
	ci|prod|-ci|-prod)
		ask="PROD"
		;;
	q|quiet|-q|-quiet)
		verbose=0
		;;
	patch)
		patch=1
		;;
	esac

	shift
done

# PRODUCTION
# -  assign rx_timerLong_resume = (rx_timerLong_counter == 23'h0e933f);
# -  assign rx_timerLong_reset = (rx_timerLong_counter == 23'h07403f);
# -  assign rx_timerLong_suspend = (rx_timerLong_counter == 23'h021fbf);
# SIM (FS 1/200)
#    assign rx_timerLong_resume = (rx_timerLong_counter == 23'h0012a7);
#    assign rx_timerLong_reset = (rx_timerLong_counter == 23'h000947);
#    assign rx_timerLong_suspend = (rx_timerLong_counter == 23'h0002b7);
# SIM (LS 1/20 current)
#          tried at 1/25 but it is on the limit of firing a spurious suspend from specification packet
#          sizes with not enough gap between tests to allow us to setup testing comfortably
#    assign rx_timerLong_resume = (rx_timerLong_counter == 23'h00ba8f);
#    assign rx_timerLong_reset = (rx_timerLong_counter == 23'h005ccf);
#    assign rx_timerLong_suspend = (rx_timerLong_counter == 23'h001b2f);
# SIM (LS 1/25 old)
#    assign rx_timerLong_resume = (rx_timerLong_counter == 23'h00953f);
#    assign rx_timerLong_reset = (rx_timerLong_counter == 23'h004a3f);
#    assign rx_timerLong_suspend = (rx_timerLong_counter == 23'h0015bf);

if [ $patch -gt 0 ]
then
	cp UsbDeviceTop.v UsbDeviceTop.v.gds_orig

	if [ "$ask" = "FS" ]
	then
		target__resume="0012a7"
		target___reset="000947"
		target_suspend="0002b7"
	elif [ "$ask" = "LS" ]		# 1/20 current
	then
		target__resume="00ba8f"
		target___reset="005ccf"
		target_suspend="001b2f"
	elif [ "$ask" = "LS25" ]	# 1/25 old
	then
		target__resume="00953f"
		target___reset="004a3f"
		target_suspend="0015bf"
	else	# PRODUCTION
		target__resume="0e933f"
		target___reset="07403f"
		target_suspend="021fbf"
	fi

	# FS
	sed -e "s#rx_timerLong_counter == \(2[13]\)'h0012a7#rx_timerLong_counter == \1'h${target__resume}#" -i UsbDeviceTop.v
	sed -e "s#rx_timerLong_counter == \(2[13]\)'h000947#rx_timerLong_counter == \1'h${target___reset}#" -i UsbDeviceTop.v
	sed -e "s#rx_timerLong_counter == \(2[13]\)'h0002b7#rx_timerLong_counter == \1'h${target_suspend}#" -i UsbDeviceTop.v
	# LS 1/20 (current)
	sed -e "s#rx_timerLong_counter == \(2[13]\)'h00ba8f#rx_timerLong_counter == \1'h${target__resume}#" -i UsbDeviceTop.v
	sed -e "s#rx_timerLong_counter == \(2[13]\)'h005ccf#rx_timerLong_counter == \1'h${target___reset}#" -i UsbDeviceTop.v
	sed -e "s#rx_timerLong_counter == \(2[13]\)'h001b2f#rx_timerLong_counter == \1'h${target_suspend}#" -i UsbDeviceTop.v
	# LS 1/25 (old)
	sed -e "s#rx_timerLong_counter == \(2[13]\)'h00953f#rx_timerLong_counter == \1'h${target__resume}#" -i UsbDeviceTop.v
	sed -e "s#rx_timerLong_counter == \(2[13]\)'h004a3f#rx_timerLong_counter == \1'h${target___reset}#" -i UsbDeviceTop.v
	sed -e "s#rx_timerLong_counter == \(2[13]\)'h0015bf#rx_timerLong_counter == \1'h${target_suspend}#" -i UsbDeviceTop.v
	# PRODUCTION 48MHz
	sed -e "s#rx_timerLong_counter == \(2[13]\)'h0e933f#rx_timerLong_counter == \1'h${target__resume}#" -i UsbDeviceTop.v
	sed -e "s#rx_timerLong_counter == \(2[13]\)'h07403f#rx_timerLong_counter == \1'h${target___reset}#" -i UsbDeviceTop.v
	sed -e "s#rx_timerLong_counter == \(2[13]\)'h021fbf#rx_timerLong_counter == \1'h${target_suspend}#" -i UsbDeviceTop.v

	diff -u UsbDeviceTop.v.gds_orig UsbDeviceTop.v || true
fi


grep_resume=$( egrep -s "rx_timerLong_resume = .*'h[0-9a-f]+\W" $VERILOG_FILE)
grep_reset=$(  egrep -s "rx_timerLong_reset = .*'h[0-9a-f]+\W" $VERILOG_FILE)
grep_suspend=$(egrep -s "rx_timerLong_suspend = .*'h[0-9a-f]+\W" $VERILOG_FILE)

if [ -z "$grep_resume" ] || [ -z "$grep_reset" ] || [ -z "$grep_suspend" ]
then
	echo "$0: ERROR unable to find values in file: $VERILOG_FILE"
	exit 1
fi

found="unknown"

if      echo -n "$grep_resume"  | egrep -q "'h0e933f\W" &&
	echo -n "$grep_reset"   | egrep -q "'h07403f\W" &&
	echo -n "$grep_suspend" | egrep -q "'h021fbf\W"
then
	if [ $verbose -gt 0 ]
	then
		echo "### $grep_resume"
		echo "### $grep_reset"
		echo "### $grep_suspend"
		echo "#################################################"
		echo "$VERILOG_FILE: PRODUCTION clock 48MHz"
	fi
	found="PROD"
fi

if      echo -n "$grep_resume"  | egrep -q "'h0012a7\W" &&
	echo -n "$grep_reset"   | egrep -q "'h000947\W" &&
	echo -n "$grep_suspend" | egrep -q "'h0002b7\W"
then
	if [ $verbose -gt 0 ]
	then
		echo "### $grep_resume"
		echo "### $grep_reset"
		echo "### $grep_suspend"
		echo "#################################################"
		echo "$VERILOG_FILE: FULL_SPEED simulation only 1/200"
	fi
	found="FS"
fi

if      echo -n "$grep_resume"  | egrep -q "'h00ba8f\W" &&
	echo -n "$grep_reset"   | egrep -q "'h005ccf\W" &&
	echo -n "$grep_suspend" | egrep -q "'h001b2f\W"
then
	if [ $verbose -gt 0 ]
	then
		echo "### $grep_resume"
		echo "### $grep_reset"
		echo "### $grep_suspend"
		echo "#################################################"
		echo "$VERILOG_FILE: LOW_SPEED simulation only 1/20"
	fi
	found="LS"
fi

if      echo -n "$grep_resume"  | egrep -q "'h00953f\W" &&
	echo -n "$grep_reset"   | egrep -q "'h004a3f\W" &&
	echo -n "$grep_suspend" | egrep -q "'h0015bf\W"
then
	if [ $verbose -gt 0 ]
	then
		echo "### $grep_resume"
		echo "### $grep_reset"
		echo "### $grep_suspend"
		echo "#################################################"
		echo "$VERILOG_FILE: LOW_SPEED simulation only 1/25 (old)"
	fi
	found="LS"
fi


if [ "$ask" = "$found" ]
then
	exit 0
fi

[ $verbose -gt 0 ] && echo "FAIL: exit=1"
exit 1
