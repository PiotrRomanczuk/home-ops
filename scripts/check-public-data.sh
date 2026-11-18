#!/usr/bin/env bash
# Gate for the public repo: reject personal data in the lines a branch ADDS.
# Checks `git diff --unified=0 "${BASE:-origin/dev}"...HEAD` for e-mail addresses,
# PL phone numbers, MAC addresses and data:image in docs/manual-tests/ without
# the data-demo="true" marker, and image files added under docs/. Prints `file:line: kind` (never the value); exit 1 on any hit.
# Exceptions: scripts/public-data-allowlist.txt (override path with ALLOWLIST).
set -euo pipefail

base="${BASE:-origin/dev}"
if ! { git rev-parse --verify -q "${base}^{commit}" >/dev/null && git merge-base "$base" HEAD >/dev/null; }; then
  echo "check-public-data: base ${base} not found or no merge base (fetch-depth 0?)" >&2
  exit 2
fi
allowlist="${ALLOWLIST:-$(dirname "$0")/public-data-allowlist.txt}"
marker='data-demo="true"'

# Scripts that must quote the patterns they look for.
self_paths='^scripts/(check-public-data\.sh|public-data-allowlist\.txt|tests/test_check_public_data\.sh)$'

email_re='[A-Za-z0-9._%+-]+@([A-Za-z0-9-]+\.)+[A-Za-z]{2,}'
phone_re='(\+48[ -]?[0-9]{3}[ -]?[0-9]{3}[ -]?[0-9]{3}|(^|[^0-9])[0-9]{3}[ -][0-9]{3}[ -][0-9]{3}([^0-9]|$))'
mac_re='(^|[^0-9A-Fa-f:-])([0-9A-Fa-f]{2}[:-]){5}[0-9A-Fa-f]{2}([^0-9A-Fa-f:-]|$)'

# Allowlist lines: `file:<ERE>` skips files whose path matches; anything else is an
# ERE tested against the matched value. Blank lines and `#` comments are ignored.
value_rules=()
file_rules=()
if [[ -f "$allowlist" ]]; then
  while IFS= read -r rule; do
    [[ -z "$rule" || "$rule" == \#* ]] && continue
    if [[ "$rule" == file:* ]]; then file_rules+=("${rule#file:}"); else value_rules+=("$rule"); fi
  done < "$allowlist"
fi

is_allowed_value() {
  local value="$1" rule
  for rule in "${value_rules[@]+"${value_rules[@]}"}"; do
    if grep -Eqi -- "$rule" <<< "$value"; then return 0; fi
  done
  return 1
}

is_allowed_file() {
  local path="$1" rule
  for rule in "${file_rules[@]+"${file_rules[@]}"}"; do
    if grep -Eq -- "$rule" <<< "$path"; then return 0; fi
  done
  return 1
}

# Added lines as `path<TAB>line<TAB>text`.
added_lines() {
  git -c core.quotePath=false diff --unified=0 --no-color --no-ext-diff "${base}...HEAD" | awk '
    /^diff --git / { hdr = 1; next }
    hdr && /^\+\+\+ / { path = ($2 == "/dev/null") ? "" : substr($0, 7); next }
    /^@@ / { hdr = 0; match($0, /\+[0-9]+/); line = substr($0, RSTART + 1, RLENGTH - 1) + 0; next }
    /^\+/ && path != "" { printf "%s\t%d\t%s\n", path, line, substr($0, 2); line++ }
  '
}

status=0
report() { printf '%s:%s: %s\n' "$1" "$2" "$3"; status=1; }

while IFS=$'\t' read -r path line text; do
  [[ "$path" =~ $self_paths ]] && continue
  is_allowed_file "$path" && continue

  if [[ "$path" == docs/manual-tests/* && "$text" == *"data:image/"* ]]; then
    if ! grep -qF -- "$marker" "$path" 2>/dev/null; then
      report "$path" "$line" "data:image without ${marker}"
    fi
  fi
  # Drop inline images so base64 noise never matches the patterns below.
  text="$(sed -E 's#data:image/[^"'"'"') ]*#IMG#g' <<< "$text")"

  while IFS= read -r value; do
    [[ -z "$value" ]] && continue
    is_allowed_value "$value" || report "$path" "$line" "e-mail"
  done < <(grep -Eo -- "$email_re" <<< "$text" || true)

  if grep -Eq -- "$phone_re" <<< "$text"; then
    value="$(grep -Eo -- "$phone_re" <<< "$text" | head -n1)"
    is_allowed_value "$value" || report "$path" "$line" "phone number"
  fi
  if grep -Eq -- "$mac_re" <<< "$text"; then
    value="$(grep -Eo -- "$mac_re" <<< "$text" | head -n1)"
    is_allowed_value "$value" || report "$path" "$line" "MAC address"
  fi
done < <(added_lines)

image_pathspecs=()
for ext in png jpg jpeg webp gif svg heic avif bmp tif tiff; do image_pathspecs+=(":(icase)docs/*.${ext}"); done

# Screenshots committed as files under docs/ (binary, so the line scan cannot see them).
while IFS= read -r path; do
  [[ -z "$path" ]] && continue
  is_allowed_file "$path" && continue
  report "$path" 0 "image file"
done < <(git -c core.quotePath=false diff --name-only --diff-filter=AM "${base}...HEAD" -- "${image_pathspecs[@]}")

if [[ "$status" -ne 0 ]]; then
  echo "check-public-data: this repo is public. Remove the data, use demo data, or add a justified rule to scripts/public-data-allowlist.txt" >&2
fi
exit "$status"
