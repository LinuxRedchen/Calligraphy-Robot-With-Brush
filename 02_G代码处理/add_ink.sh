#!/usr/bin/env bash
# ============================================================
# 奎享雕刻 · 画画蘸墨后处理脚本（修正版）
# 作用：在导出的 G 代码里，每累计画满一定长度，就在抬笔处插入一次蘸墨动作，
#       蘸完墨后回到原断点继续画。
# 用法：./add_ink.sh 输入文件.gcode [输出文件.gcode]
#       不写输出文件时，自动生成「输入文件_蘸墨.gcode」
#
# 本机（奎享雕刻/默认 Grbl 机器）导出的 G 代码格式（没有空格、F 固定）：
#   抬笔  G1G90 Z0.0F10000
#   落笔  G1G90 Z5.0F10000
#   移动  G0 X18.256Y6.085F10000
#   画线  G1 X17.198Y6.350F10000
#   回零  G90G0 X0Y0
# 下面的插入动作严格按这个格式生成，才能被软件/机器认出来。
# ============================================================

# ------------------ 参数区（以后只改这里） ------------------
INK_X=100          # 墨盘 X 坐标（毫米）★ 改成你墨盘实际位置
INK_Y=100          # 墨盘 Y 坐标（毫米）★ 同上
INK_Z=5            # 蘸墨时笔尖下压深度（落笔 Z，一般等于机器落笔高度）
INK_UP_Z=0         # 蘸墨抬笔 Z（一般等于机器抬笔高度）
INK_DWELL=0.8      # 蘸墨停留时间（秒），用来吸墨；设 0 就不插 G4 停留
INK_EVERY=400      # 每累计画满多少毫米，就蘸一次墨（想蘸勤点就调小）
PEN_DOWN_Z=5       # 机器「落笔」对应的 Z 值（步进电机模式默认 5）
PEN_UP_Z=0         # 机器「抬笔」对应的 Z 值（步进电机模式默认 0）
FEED=10000         # 移动/Z 的 F 速度（与导出文件的 F10000 一致）
SCRAPE_ON=1        # 1=蘸墨后刮墨，0=不刮墨
MOVE_DIST=30       # 蘸墨后先从墨盘移开多远（毫米），离开墨盘再刮墨
MOVE_DIR=right     # 移开方向：right(+X)/left(-X)/down(+Y)/up(-Y)
SCRAPE_DIR=right   # 刮墨滑动方向：right(+X)/left(-X)/down(+Y)/up(-Y)
SCRAPE_DIST=20     # 刮墨滑动距离（毫米）
SCRAPE_Z=5         # 刮墨下压 Z（一般等于落笔 Z）
# ------------------------------------------------------------

INPUT="${1:?用法: $0 输入.gcode [输出.gcode]}"
OUTPUT="${2:-${INPUT%.gcode}_蘸墨.gcode}"

awk -v ink_x="$INK_X" -v ink_y="$INK_Y" -v ink_z="$INK_Z" \
    -v ink_up="$INK_UP_Z" -v dwell="$INK_DWELL" -v every="$INK_EVERY" \
    -v zdown="$PEN_DOWN_Z" -v zup="$PEN_UP_Z" -v feed="$FEED" \
    -v scrape_on="$SCRAPE_ON" -v move_dir="$MOVE_DIR" -v move_dist="$MOVE_DIST" \
    -v scrape_dir="$SCRAPE_DIR" -v scrape_dist="$SCRAPE_DIST" -v scrape_z="$SCRAPE_Z" '
function dist(x1, y1, x2, y2) { dx=x2-x1; dy=y2-y1; return sqrt(dx*dx+dy*dy) }

# 插入一次蘸墨：当前笔是抬起的，先去墨盘蘸墨，再回到断点（仍抬笔），
# 后面原来的 G0/G1G90 会自动继续。
function emit(px, py) {
    printf "G0 X%.3fY%.3fF%d\r\n", ink_x, ink_y, feed   # 抬笔去墨盘
    printf "G1G90 Z%.1fF%d\r\n", ink_z, feed            # 落笔蘸墨
    if (dwell > 0) printf "G4 P%.2f\r\n", dwell         # 停留吸墨（dwell=0 则不插）
    printf "G1G90 Z%.1fF%d\r\n", ink_up, feed           # 抬笔
    if (scrape_on) {
        # 蘸墨后先从墨盘移开一段距离，离开墨盘再刮墨
        mx = 0; my = 0
        if (move_dir == "left")      mx = -move_dist
        else if (move_dir == "down") my =  move_dist
        else if (move_dir == "up")   my = -move_dist
        else                         mx =  move_dist   # right
        sx = ink_x + mx; sy = ink_y + my                 # 刮墨起点
        # 刮墨滑动
        dx = 0; dy = 0
        if (scrape_dir == "left")      dx = -scrape_dist
        else if (scrape_dir == "down") dy =  scrape_dist
        else if (scrape_dir == "up")   dy = -scrape_dist
        else                           dx =  scrape_dist   # right
        ex = sx + dx; ey = sy + dy                       # 刮墨终点
        printf "G0 X%.3fY%.3fF%d\r\n", sx, sy, feed       # 移到刮墨点
        printf "G1G90 Z%.1fF%d\r\n", scrape_z, feed       # 下压刮墨
        printf "G1 X%.3fY%.3fF%d\r\n", ex, ey, feed       # 滑动刮墨
        printf "G1G90 Z%.1fF%d\r\n", ink_up, feed         # 抬笔
    }
    printf "G0 X%.3fY%.3fF%d\r\n", px, py, feed         # 回到断点
}

BEGIN { ORS="\r\n"; pen=0; px=0; py=0; have=0; total=0; pending=0; hold=0; ink_count=0 }
{
    line = $0
    sub(/\r$/, "", line)   # 去掉可能残留的 \r，下面统一按 CRLF 输出（与原文件一致）

    # 上一行挂起的蘸墨：如果下一行是回零(0,0)，说明已到文件末尾，交给软件 endGcode，跳过
    if (hold) {
        hold = 0
        is_home = (match(line, /X(-?[0-9.]+)Y(-?[0-9.]+)/, mh) && (mh[1]+0==0) && (mh[2]+0==0))
        if (!is_home) { emit(px, py); ink_count++ }
    }

    # 1) 识别抬笔 / 落笔（按 Z 值）
    if (match(line, /Z(-?[0-9.]+)/, mz)) {
        z = mz[1] + 0
        if (z == zup) {
            print line
            if (pending) { hold = 1; pending = 0; total = 0 }
            pen = 0
            next
        }
        if (z == zdown) {
            pen = 1
            print line
            next
        }
    }
    # 2) 落笔状态下累加画的长度（G1 X..Y.. 移动）
    if (pen == 1 && match(line, /X(-?[0-9.]+)Y(-?[0-9.]+)/, mxy)) {
        x = mxy[1] + 0; y = mxy[2] + 0
        if (have == 1) {
            total += dist(px, py, x, y)
            if (total >= every) pending = 1
        }
        px = x; py = y; have = 1
    } else if (match(line, /X(-?[0-9.]+)Y(-?[0-9.]+)/, mxy)) {
        # 抬笔状态下的 G0 移动：只更新笔尖位置，不累计
        px = mxy[1] + 0; py = mxy[2] + 0; have = 1
    }
    print line
}
END { printf "共插入 %d 次蘸墨\n", ink_count > "/dev/stderr" }
' "$INPUT" > "$OUTPUT"

echo "已生成：$OUTPUT"
