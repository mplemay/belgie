#!/usr/bin/env bash
set -euo pipefail

: "${VERSION:?VERSION is required}"
: "${EXPECTED_WHEELS:=8}"

wheel_count="$(find dist -maxdepth 1 -type f -name 'belgie-*.whl' | wc -l | tr -d ' ')"
sdist_count="$(find dist -maxdepth 1 -type f -name 'belgie-*.tar.gz' | wc -l | tr -d ' ')"

if [[ "$wheel_count" != "$EXPECTED_WHEELS" ]]; then
  echo "::error::Expected $EXPECTED_WHEELS wheels, found $wheel_count."
  find dist -maxdepth 1 -type f -print
  exit 1
fi

if [[ "$sdist_count" != "1" ]]; then
  echo "::error::Expected 1 source distribution, found $sdist_count."
  find dist -maxdepth 1 -type f -print
  exit 1
fi

for artifact in dist/*; do
  filename="$(basename "$artifact")"
  if [[ "$filename" != belgie-"$VERSION"-* && "$filename" != belgie-"$VERSION".tar.gz ]]; then
    echo "::error::Unexpected distribution filename: $filename"
    exit 1
  fi
done

wheels=()
while IFS= read -r wheel; do
  wheels+=("$wheel")
done < <(find dist -maxdepth 1 -type f -name 'belgie-*.whl' -print | sort)

declare -A required_tags=(
  [manylinux_2_28_x86_64]=0
  [manylinux_2_28_aarch64]=0
  [musllinux_1_2_x86_64]=0
  [musllinux_1_2_aarch64]=0
  [macosx_x86_64]=0
  [macosx_arm64]=0
  [win_amd64]=0
  [win_arm64]=0
)

for wheel in "${wheels[@]}"; do
  filename="$(basename "$wheel")"
  matched=false

  if [[ "$filename" == *manylinux_2_28_x86_64.whl ]]; then
    required_tags[manylinux_2_28_x86_64]=1
    matched=true
  elif [[ "$filename" == *manylinux_2_28_aarch64.whl ]]; then
    required_tags[manylinux_2_28_aarch64]=1
    matched=true
  elif [[ "$filename" == *musllinux_1_2_x86_64.whl ]]; then
    required_tags[musllinux_1_2_x86_64]=1
    matched=true
  elif [[ "$filename" == *musllinux_1_2_aarch64.whl ]]; then
    required_tags[musllinux_1_2_aarch64]=1
    matched=true
  elif [[ "$filename" == *macosx_*_x86_64.whl ]]; then
    required_tags[macosx_x86_64]=1
    matched=true
  elif [[ "$filename" == *macosx_*_arm64.whl || "$filename" == *macosx_*_aarch64.whl ]]; then
    required_tags[macosx_arm64]=1
    matched=true
  elif [[ "$filename" == *win_amd64.whl ]]; then
    required_tags[win_amd64]=1
    matched=true
  elif [[ "$filename" == *win_arm64.whl ]]; then
    required_tags[win_arm64]=1
    matched=true
  fi

  if [[ "$matched" == false ]]; then
    echo "::error::Unrecognized wheel platform tag: $filename"
    exit 1
  fi
done

missing_tags=()
for tag in "${!required_tags[@]}"; do
  if [[ "${required_tags[$tag]}" -eq 0 ]]; then
    missing_tags+=("$tag")
  fi
done

if ((${#missing_tags[@]} > 0)); then
  echo "::error::Missing required wheel platform tags: ${missing_tags[*]}"
  exit 1
fi
