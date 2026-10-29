#!/usr/bin/env bash
# Screenshots of the local site with headless Chrome. Usage: bash scripts_screens.sh [base_url]
B=${1:-http://127.0.0.1:8000}; O=screens; mkdir -p $O
shot(){ google-chrome --headless=new --no-sandbox --disable-gpu --hide-scrollbars --window-size=$3 --virtual-time-budget=9000 --screenshot=$O/$1.png "$B/$2" >/dev/null 2>&1; echo "$O/$1.png"; }
shot 01_home_zh "?lang=zh#/" 1360,2000
shot 02_home_en "?lang=en#/" 1360,2000
shot 03_members_zh "?lang=zh#/members" 1360,1000
shot 04_member_zh "?lang=zh#/member/$MEMBER" 1360,1500
shot 05_ticker_en "?lang=en#/ticker/NVDA" 1360,1500
shot 06_track_zh "?lang=zh#/track" 1360,1700
shot 07_track_en "?lang=en#/track" 1360,1700
shot 08_about_zh "?lang=zh#/about" 1360,1000
shot 09_home_mobile_zh "?lang=zh#/" 420,2200
shot 10_consensus_zh "?lang=zh#/?open=1" 1360,1150
shot 10_consensus_en "?lang=en#/?open=1" 1360,1150
shot 11_consensus_30d_zh "?lang=zh#/?cw=30" 1360,900
shot 12_consensus_mobile_zh "?lang=zh#/?open=1" 420,1500
# 13: big single-member section, cropped from a tall shot (crop box found by the light-gray #cs-big divider line)
for L in zh en; do google-chrome --headless=new --no-sandbox --disable-gpu --hide-scrollbars --window-size=1360,2200 --virtual-time-budget=9000 --screenshot=/tmp/_tall_$L.png "$B/?lang=$L#/" >/dev/null 2>&1
  .venv/bin/python -c "
from PIL import Image; im=Image.open('/tmp/_tall_$L.png').convert('RGB'); W,H=im.size
x=W//2; y0=next(y for y in range(300,H) if im.getpixel((x,y))==(227,230,239) and im.getpixel((x,y+1))==(227,230,239))
y1=next((y for y in range(y0+60,H) if all(im.getpixel((xx,y))==(245,246,250) for xx in (60,W//2,W-60))), H)
im.crop((0,max(0,y0-20),W,min(H,y1+10))).save('$O/13_big_single_$L.png')"; echo $O/13_big_single_$L.png; done
# 14: picks method toggle (cropped from a tall shot at the segmented control, color #1f3a8a); zh = 議員共識 (default), en = Backtest-best (?m=v1)
for X in "zh|" "en|&m=v1"; do L=${X%%|*}; Q=${X#*|}
  google-chrome --headless=new --no-sandbox --disable-gpu --hide-scrollbars --window-size=1360,4600 --virtual-time-budget=9000 --screenshot=/tmp/_pk_$L.png "$B/?lang=$L#/?x=1$Q" >/dev/null 2>&1
  .venv/bin/python - "$L" "$O" <<'PY'
import sys; from PIL import Image
L, O = sys.argv[1:]; im = Image.open(f"/tmp/_pk_{L}.png").convert("RGB"); w, h = im.size; px = im.load()
y = next(y for y in range(h) if sum(abs(px[x, y][0]-31)+abs(px[x, y][1]-58)+abs(px[x, y][2]-138) < 30 for x in range(0, w, 2)) > 30)
im.crop((0, max(0, y - 70), w, min(h, y + 1250))).save(f"{O}/14_picks_toggle_{L}.png"); print(f"{O}/14_picks_toggle_{L}.png")
PY
done
shot 15_trackrecord_compare_zh "?lang=zh#/track" 1360,2900
