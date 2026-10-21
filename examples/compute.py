import signal
import time

signal.alarm(5)
deadline = time.monotonic() + 4
print("Starting finite computation", flush=True)
value = 0
for _ in range(100_000_000):
    value = (value + 1) % 1000003
    if value % 10000 == 0 and time.monotonic() >= deadline:
        break
print("Computation finished without CPU-signal termination")
