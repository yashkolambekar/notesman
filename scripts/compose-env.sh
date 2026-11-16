#!/bin/sh
# Print the variables docker-compose.yml needs, as a template for Coolify's "Developer view".
grep -oE '\$\{[A-Z0-9_]+(:[-?])?[^}]*\}' docker-compose.yml | sed -E 's/^\$\{([A-Z0-9_]+).*$/\1=/' | sort -u
