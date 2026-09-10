#!/usr/bin/env bash
# Status line: session cost, context window usage bar, current model,
# rate-limit remainders (5h session / 7d weekly), and week/month spend.
set -uo pipefail

input=$(cat)

model_name=$(printf '%s' "$input" | jq -r '.model.display_name // "Claude"')

used_pct=$(printf '%s' "$input" | jq -r '.context_window.used_percentage // 0')
used_pct_int=$(printf '%.0f' "${used_pct:-0}" 2>/dev/null || echo 0)
[ -z "$used_pct_int" ] && used_pct_int=0
[ "$used_pct_int" -gt 100 ] && used_pct_int=100
[ "$used_pct_int" -lt 0 ] && used_pct_int=0

bar_width=20
filled=$((used_pct_int * bar_width / 100))
empty=$((bar_width - filled))

bar=$(printf '%*s' "$filled" '' | tr ' ' '#')$(printf '%*s' "$empty" '' | tr ' ' '-')

if [ "$used_pct_int" -ge 80 ]; then
    bar_color=$'\033[2;31m'
elif [ "$used_pct_int" -ge 50 ]; then
    bar_color=$'\033[2;33m'
else
    bar_color=$'\033[2;32m'
fi
dim=$'\033[2m'
reset=$'\033[0m'
red=$'\033[2;31m'
yellow=$'\033[2;33m'
green=$'\033[2;32m'

# Color by remaining%, not used% - low remaining is the danger direction here.
color_for_remaining() {
    local remaining="$1"
    if [ "$remaining" -le 20 ]; then
        printf '%s' "$red"
    elif [ "$remaining" -le 50 ]; then
        printf '%s' "$yellow"
    else
        printf '%s' "$green"
    fi
}

# Compact "time until epoch" like "2h14m" / "3d5h" / "now".
relative_time() {
    local target="$1" now diff
    now=$(date +%s)
    diff=$((target - now))
    [ "$diff" -le 0 ] && { printf 'now'; return; }
    if [ "$diff" -lt 3600 ]; then
        printf '%dm' "$((diff / 60))"
    elif [ "$diff" -lt 86400 ]; then
        printf '%dh%dm' "$((diff / 3600))" "$(((diff % 3600) / 60))"
    else
        printf '%dd%dh' "$((diff / 86400))" "$(((diff % 86400) / 3600))"
    fi
}

# Per-MTok list rates. Cache write is 1.25x input (5m TTL) / 2x (1h); read is 0.1x.
# An unrecognised model yields a null cost, rendered as "$?" rather than a wrong number.
# shellcheck disable=SC2016 # jq script: $m below is jq's own variable, not bash's.
COST_RATES_JQ='
  def rates($m):
    if   ($m == "<synthetic>")       then {i: 0,  o: 0}
    elif ($m | test("fable|mythos")) then {i: 10, o: 50}
    elif ($m | test("haiku"))        then {i: 1,  o: 5}
    elif ($m | test("sonnet"))       then {i: 3,  o: 15}
    elif ($m | test("opus-4-(0|1)")) then {i: 15, o: 75}
    elif ($m | test("opus"))         then {i: 5,  o: 25}
    else null end;

  [ .[]
    | select(.type == "assistant" and .message.usage != null and ((.isSidechain // false) == false))
    | .message.usage as $u
    | rates(.message.model // "")
    | if . == null then null else
        .i as $i
        | ( ($u.cache_creation.ephemeral_5m_input_tokens // $u.cache_creation_input_tokens // 0) * $i * 1.25
          + ($u.cache_creation.ephemeral_1h_input_tokens // 0)                                  * $i * 2
          + ($u.cache_read_input_tokens // 0)                                                   * $i * 0.1
          + ($u.input_tokens  // 0)                                                             * $i
          + ($u.output_tokens // 0)                                                             * .o
          ) / 1000000
      end
  ] as $costs
  | if ($costs | any(. == null)) then "?" else (($costs | add) // 0) end
'

# Same rate table, but bucketed by each message's own timestamp (not file mtime) into
# day/week/month sums in one pass. A file touched today can still hold messages from
# last week; per-message timestamp filtering keeps those out of the "day" bucket.
# shellcheck disable=SC2016
BUCKETED_COST_JQ='
  def rates($m):
    if   ($m == "<synthetic>")       then {i: 0,  o: 0}
    elif ($m | test("fable|mythos")) then {i: 10, o: 50}
    elif ($m | test("haiku"))        then {i: 1,  o: 5}
    elif ($m | test("sonnet"))       then {i: 3,  o: 15}
    elif ($m | test("opus-4-(0|1)")) then {i: 15, o: 75}
    elif ($m | test("opus"))         then {i: 5,  o: 25}
    else null end;

  def bucket_sum($since):
    map(select(.ts >= $since) | .cost)
    | if any(. == null) then "?" else (add // 0) end;

  [ .[]
    | select(.type == "assistant" and .message.usage != null and ((.isSidechain // false) == false) and (.timestamp != null))
    | (.timestamp | sub("\\.[0-9]+Z$"; "Z") | fromdateiso8601) as $ts
    | .message.usage as $u
    | rates(.message.model // "") as $r
    | { ts: $ts,
        cost: ( if $r == null then null else
            $r.i as $i
            | ( ($u.cache_creation.ephemeral_5m_input_tokens // $u.cache_creation_input_tokens // 0) * $i * 1.25
              + ($u.cache_creation.ephemeral_1h_input_tokens // 0)                                  * $i * 2
              + ($u.cache_read_input_tokens // 0)                                                   * $i * 0.1
              + ($u.input_tokens  // 0)                                                             * $i
              + ($u.output_tokens // 0)                                                             * $r.o
              ) / 1000000
          end )
      }
  ] as $entries
  | { day:   ($entries | bucket_sum($day_epoch)),
      week:  ($entries | bucket_sum($week_epoch)),
      month: ($entries | bucket_sum($month_epoch)) }
'

transcript_path=$(printf '%s' "$input" | jq -r '.transcript_path // empty')
cost=""
if [ -n "$transcript_path" ] && [ -f "$transcript_path" ]; then
    # -r is load-bearing: a quoted "12.34" makes bash printf read the leading
    # double-quote as a character-code literal and emit a wrong number silently.
    cost=$(jq -sr "$COST_RATES_JQ" "$transcript_path" 2>/dev/null)
fi
[ -z "$cost" ] && cost="?"
if [ "$cost" != "?" ]; then
    cost=$(printf '%.2f' "$cost" 2>/dev/null || echo "?")
fi

line1=$(printf "%s\$%s%s  %s%s%s %s%d%%%s  %s%s%s" \
    "$dim" "$cost" "$reset" \
    "$bar_color" "$bar" "$reset" "$dim" "$used_pct_int" "$reset" \
    "$dim" "$model_name" "$reset")

# --- Rate limits: 5h session window + 7d weekly window (Anthropic exposes no daily window). ---
five_hour_used=$(printf '%s' "$input" | jq -r '.rate_limits.five_hour.used_percentage // empty')
five_hour_resets=$(printf '%s' "$input" | jq -r '.rate_limits.five_hour.resets_at // empty')
seven_day_used=$(printf '%s' "$input" | jq -r '.rate_limits.seven_day.used_percentage // empty')
seven_day_resets=$(printf '%s' "$input" | jq -r '.rate_limits.seven_day.resets_at // empty')

rate_limit_segment=""
if [ -n "$five_hour_used" ] || [ -n "$seven_day_used" ]; then
    parts=()
    if [ -n "$five_hour_used" ]; then
        fh_used_int=$(printf '%.0f' "$five_hour_used" 2>/dev/null || echo 0)
        fh_remaining=$((100 - fh_used_int))
        fh_color=$(color_for_remaining "$fh_remaining")
        fh_when=""
        [ -n "$five_hour_resets" ] && fh_when=$(relative_time "$five_hour_resets")
        parts+=("${dim}5h${reset} ${fh_color}${fh_remaining}%${reset}${fh_when:+${dim}(${fh_when})${reset}}")
    fi
    if [ -n "$seven_day_used" ]; then
        sd_used_int=$(printf '%.0f' "$seven_day_used" 2>/dev/null || echo 0)
        sd_remaining=$((100 - sd_used_int))
        sd_color=$(color_for_remaining "$sd_remaining")
        sd_when=""
        [ -n "$seven_day_resets" ] && sd_when=$(relative_time "$seven_day_resets")
        parts+=("${dim}wk${reset} ${sd_color}${sd_remaining}%${reset}${sd_when:+${dim}(${sd_when})${reset}}")
    fi
    IFS=' '; rate_limit_segment="${parts[*]}"; unset IFS
fi

# --- Day/week/month total spend, cached in the background so this never blocks the render. ---
# Daily $50 budget is self-imposed (work account, API-metered) - Anthropic exposes no daily
# rate-limit window, unlike the personal Pro account's 5h session window shown above.
DAILY_BUDGET=50
cache_dir="$HOME/.cache/claude-statusline"
mkdir -p "$cache_dir" 2>/dev/null
daily_cache="$cache_dir/daily_cost.cache"
weekly_cache="$cache_dir/weekly_cost.cache"
monthly_cache="$cache_dir/monthly_cost.cache"
lock_dir="$cache_dir/.spend.lock"
cache_ttl=300

now_epoch=$(date +%s)
daily_spend=""
weekly_spend=""
monthly_spend=""
[ -f "$daily_cache" ] && daily_spend=$(cat "$daily_cache" 2>/dev/null)
[ -f "$weekly_cache" ] && weekly_spend=$(cat "$weekly_cache" 2>/dev/null)
[ -f "$monthly_cache" ] && monthly_spend=$(cat "$monthly_cache" 2>/dev/null)

weekly_cache_age=$cache_ttl
if [ -f "$weekly_cache" ]; then
    weekly_cache_age=$((now_epoch - $(stat -c %Y "$weekly_cache" 2>/dev/null || stat -f %m "$weekly_cache" 2>/dev/null || echo 0)))
fi

if [ "$weekly_cache_age" -ge "$cache_ttl" ] && mkdir "$lock_dir" 2>/dev/null; then
    (
        trap 'rmdir "$lock_dir" 2>/dev/null' EXIT
        projects_dir="$HOME/.claude/projects"
        day_since=$(date '+%Y-%m-%d')
        week_since=$(date -d '7 days ago' '+%Y-%m-%d' 2>/dev/null || date -v-7d '+%Y-%m-%d' 2>/dev/null)
        month_since=$(date '+%Y-%m-01')

        # find is mtime-filtered on the widest (month) window purely to skip untouched
        # files before invoking jq; the actual day/week/month split happens per-message
        # inside BUCKETED_COST_JQ, keyed off each message's own timestamp.
        day_epoch=$(date -d "$day_since" +%s 2>/dev/null || date -j -f '%Y-%m-%d' "$day_since" +%s 2>/dev/null)
        week_epoch=$(date -d "$week_since" +%s 2>/dev/null || date -j -f '%Y-%m-%d' "$week_since" +%s 2>/dev/null)
        month_epoch=$(date -d "$month_since" +%s 2>/dev/null || date -j -f '%Y-%m-%d' "$month_since" +%s 2>/dev/null)

        if [ -n "$day_epoch" ] && [ -n "$week_epoch" ] && [ -n "$month_epoch" ]; then
            result=$(command find "$projects_dir" -iname "*.jsonl" -newermt "$month_since" -print0 2>/dev/null \
                | xargs -0 -r jq -s \
                    --argjson day_epoch "$day_epoch" \
                    --argjson week_epoch "$week_epoch" \
                    --argjson month_epoch "$month_epoch" \
                    "$BUCKETED_COST_JQ" 2>/dev/null)

            if [ -n "$result" ]; then
                d=$(printf '%s' "$result" | jq -r '.day')
                w=$(printf '%s' "$result" | jq -r '.week')
                m=$(printf '%s' "$result" | jq -r '.month')
                [ -n "$d" ] && [ "$d" != "?" ] && [ "$d" != "null" ] && printf '%s' "$d" > "$daily_cache.tmp" && mv "$daily_cache.tmp" "$daily_cache"
                [ -n "$w" ] && [ "$w" != "?" ] && [ "$w" != "null" ] && printf '%s' "$w" > "$weekly_cache.tmp" && mv "$weekly_cache.tmp" "$weekly_cache"
                [ -n "$m" ] && [ "$m" != "?" ] && [ "$m" != "null" ] && printf '%s' "$m" > "$monthly_cache.tmp" && mv "$monthly_cache.tmp" "$monthly_cache"
            fi
        fi
    ) >/dev/null 2>&1 &
    disown
fi

spend_segment=""
if [ -n "$daily_spend" ] || [ -n "$weekly_spend" ] || [ -n "$monthly_spend" ]; then
    day_fmt="?"; day_color="$dim"
    if [ -n "$daily_spend" ]; then
        day_fmt=$(printf '%.2f' "$daily_spend" 2>/dev/null || echo "?")
        if [ "$day_fmt" != "?" ]; then
            day_used_pct=$(awk -v s="$daily_spend" -v l="$DAILY_BUDGET" 'BEGIN { printf "%.0f", (l > 0 ? (s / l) * 100 : 0) }')
            day_remaining=$((100 - day_used_pct))
            [ "$day_remaining" -lt 0 ] && day_remaining=0
            day_color=$(color_for_remaining "$day_remaining")
        fi
    fi
    w_fmt="?"; [ -n "$weekly_spend" ] && w_fmt=$(printf '%.2f' "$weekly_spend" 2>/dev/null || echo "?")
    m_fmt="?"; [ -n "$monthly_spend" ] && m_fmt=$(printf '%.2f' "$monthly_spend" 2>/dev/null || echo "?")
    spend_segment="${dim}day\$${reset}${day_color}${day_fmt}${reset}${dim}/\$${DAILY_BUDGET}  wk\$${w_fmt}  mo\$${m_fmt}${reset}"
fi

out="$line1"
[ -n "$rate_limit_segment" ] && out="$out  ${dim}|${reset}  $rate_limit_segment"
[ -n "$spend_segment" ] && out="$out  ${dim}|${reset}  $spend_segment"

printf '%s\n' "$out"
