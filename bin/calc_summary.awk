##################################################
# Usage: awk -f calc_summary.awk <miner log file>
##################################################

BEGIN {
    FS="\\|"
    total_expn = 0
    total_incm = 0
    total_kwh = 0
    total_uptime_hr = 0
    total_eelec = 0
    eelec_count = 0
    prev_ts = ""
    min_delta = ""; max_delta = ""
    fallback_count = 0
}

{
    # Extract timestamp safely — ignore timezone
    split($1, ts_parts, "T")
    if (length(ts_parts) < 2) next

    split(ts_parts[1], date_parts, "-")
    split(ts_parts[2], time_parts, "-")  # remove timezone
    split(time_parts[1], clock_parts, ":")

    if (length(date_parts) != 3 || length(clock_parts) != 3) next

    year = date_parts[1]
    month = date_parts[2]
    day = date_parts[3]
    hour = clock_parts[1]
    minute = clock_parts[2]
    second = clock_parts[3]

    timestamp = mktime(year " " month " " day " " hour " " minute " " second)
    if (timestamp == -1) next

    # Extract Pwr, Expn, Incm, EElec
    pwr = expn = incm = eelec = 0
    for (i = 1; i <= NF; i++) {
        if ($i ~ /^Pwr:/) {
            split($i, pwr_parts, ":")
            pwr = gensub(/W/, "", "g", pwr_parts[2]) + 0
        }
        if ($i ~ /^Expn:/) {
            split($i, expn_parts, ":")
            expn = gensub(/\$/, "", "g", expn_parts[2]) + 0
        }
        if ($i ~ /^Incm:/) {
            split($i, incm_parts, ":")
            incm = gensub(/\$/, "", "g", incm_parts[2]) + 0
        }
        if ($i ~ /^EElec:/) {
            split($i, eelec_parts, ":")
            eelec = gensub(/¢\/kWh/, "", "g", eelec_parts[2]) + 0
            total_eelec += eelec
            eelec_count++
        }
    }

    # Accumulate Expn and Incm
    total_expn += expn
    total_incm += incm

    # Calculate kWh and uptime
    if (prev_ts == "") {
        delta_hr = 2.0 / 60
    } else {
        raw_delta_hr = (timestamp - prev_ts) / 3600
        if (raw_delta_hr > 0 && raw_delta_hr <= 0.05) {
            delta_hr = raw_delta_hr
        } else {
            delta_hr = 2.25 / 60
            fallback_count++
        }
    }

    total_uptime_hr += delta_hr
    total_kwh += (pwr / 1000) * delta_hr

    # Track min/max delta
    if (NR > 1) {
        if (min_delta == "" || delta_hr < min_delta) min_delta = delta_hr
        if (max_delta == "" || delta_hr > max_delta) max_delta = delta_hr
    }

    prev_ts = timestamp
}

END {
    avg_eelec = (total_kwh > 0) ? total_eelec / eelec_count : 0

    print  "========================================"
    printf "Summary:\n"
    printf "Total Expn: $%.6f\n", total_expn
    printf "Total Incm: $%.6f\n", total_incm
    printf "Total kWh: %.6f\n", total_kwh
    printf "Total Uptime: %.4f hours\n", total_uptime_hr
    printf "Min Δhr: %.4f, Max Δhr: %.4f\n", min_delta, max_delta
    printf "Fallbacks used: %d\n", fallback_count
    printf "EElec entries: %d\n", eelec_count
    printf "Average EElec: %.4f ¢/kWh\n", avg_eelec
    print  "========================================"
}