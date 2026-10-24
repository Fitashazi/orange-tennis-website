#!/bin/bash
set -e
DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$DIR"
UA="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"

fetch() {
  local out="$1"; shift
  for url in "$@"; do
    echo "→ $out ← $url"
    if curl -fsSL -A "$UA" -L --max-time 30 -o "$out" "$url"; then
      if file "$out" | grep -q JPEG && [ "$(wc -c < "$out")" -gt 20000 ]; then
        echo "✓ $out ($(wc -c < "$out") bytes)"
        return 0
      fi
    fi
  done
  echo "✗ failed: $out"
  return 1
}

fetch court-1.jpg \
  "https://images.unsplash.com/photo-1574629818150-04090879dbe4?w=800&q=80" \
  "https://images.pexels.com/photos/573762/pexels-photo-573762.jpeg?auto=compress&w=800" \
  "https://upload.wikimedia.org/wikipedia/commons/thumb/9/94/Tennis_court_august_2010.jpg/800px-Tennis_court_august_2010.jpg"

fetch court-2.jpg \
  "https://images.unsplash.com/photo-1554068865-24cecd4e34b8?w=800&q=80" \
  "https://images.pexels.com/photos/1148713/pexels-photo-1148713.jpeg?auto=compress&w=800"

fetch court-3.jpg \
  "https://images.unsplash.com/photo-1622279457486-62dcc4a431d6?w=800&q=80" \
  "https://images.pexels.com/photos/2330197/pexels-photo-2330197.jpeg?auto=compress&w=800"

fetch court-4.jpg \
  "https://images.unsplash.com/photo-1552319007-a038c9ac29a3?w=800&q=80" \
  "https://images.pexels.com/photos/1277219/pexels-photo-1277219.jpeg?auto=compress&w=800"

fetch court-5.jpg \
  "https://images.unsplash.com/photo-1622163644681-651b9aaffea9?w=800&q=80" \
  "https://images.pexels.com/photos/573762/pexels-photo-573762.jpeg?auto=compress&w=800"

fetch hero.jpg \
  "https://images.unsplash.com/photo-1554068865-24cecd4e34b8?w=1920&q=85" \
  "https://images.pexels.com/photos/1148713/pexels-photo-1148713.jpeg?auto=compress&w=1920"

fetch facility.jpg \
  "https://images.unsplash.com/photo-1595435934249-5df7ed397e00?w=1200&q=80" \
  "https://images.pexels.com/photos/573762/pexels-photo-573762.jpeg?auto=compress&w=1200"

echo ""
echo "Done:"
file court-*.jpg hero.jpg facility.jpg
ls -la court-*.jpg hero.jpg facility.jpg
