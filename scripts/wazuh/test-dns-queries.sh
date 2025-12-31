#!/bin/bash
# Test script for Wazuh Rule 2: Suspicious DNS Queries
# This script simulates various DNS query patterns to trigger alerts

set -e

echo "=== Wazuh Rule 2 DNS Query Test ==="
echo "This script will simulate DNS queries that should trigger alerts"
echo ""

# Test 1: Malicious domain query (Rule 100011)
echo "Test 1: Querying known malicious domain (evil.com)..."
nslookup evil.com || true
sleep 2

echo "Test 2: Querying another malicious domain (malicious-c2.com)..."
nslookup malicious-c2.com || true
sleep 2

# Test 3: Cryptocurrency mining pool query (Rule 100012)
echo "Test 3: Querying cryptocurrency mining pool (coinhive.com)..."
nslookup coinhive.com || true
sleep 2

echo "Test 4: Querying another mining pool (crypto-loot.com)..."
nslookup crypto-loot.com || true
sleep 2

# Test 5: DNS tunneling pattern (Rule 100013)
echo "Test 5: Querying suspiciously long subdomain (DNS tunneling pattern)..."
nslookup aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa.example.com || true
sleep 2

# Test 6: Repeated malicious queries (Rule 100014)
echo "Test 6: Repeated queries to malicious domain (testing frequency rule)..."
for i in {1..4}; do
  echo "  Query $i/4..."
  nslookup evil.com || true
  sleep 1
done

echo ""
echo "=== Test Complete ==="
echo "All DNS query tests executed successfully."
echo ""
echo "Expected alerts to appear in Wazuh dashboard:"
echo "  - Rule 100011: Query to known malicious domain (evil.com, malicious-c2.com)"
echo "  - Rule 100012: Query to cryptocurrency mining pool (coinhive.com, crypto-loot.com)"
echo "  - Rule 100013: Suspiciously long subdomain (DNS tunneling)"
echo "  - Rule 100014: Repeated queries to malicious domain (evil.com x4)"
echo ""
echo "Wait 60-90 seconds for events to process, then check Wazuh dashboard."
