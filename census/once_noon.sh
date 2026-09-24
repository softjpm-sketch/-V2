#!/bin/bash
LABEL="com.petamos.census.today"
rm -f "$HOME/Library/LaunchAgents/$LABEL.plist"     # 파일 먼저 제거(내일 재등록 방지)
/bin/bash "/Users/parkjungma/병원마케팅V2/census/nightly.sh" 500
launchctl bootout "gui/$(id -u)/$LABEL" 2>/dev/null # 메모리 해제(오늘만)
