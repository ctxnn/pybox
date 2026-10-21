import os
import sys


def main():
    status_fd = int(sys.argv[1])
    try:
        import resource

        soft = int(sys.argv[2])
        os.set_inheritable(status_fd, False)
        resource.setrlimit(resource.RLIMIT_CPU, (soft, soft + 1))
        if resource.getrlimit(resource.RLIMIT_CPU) != (soft, soft + 1):
            raise RuntimeError("CPU limit readback mismatch")
        os.write(status_fd, b"R")
        os.execv(sys.executable, [sys.executable, "-I", "-B", "-u", sys.argv[3]])
    except Exception:
        os.write(status_fd, b"E")
        return 125


if __name__ == "__main__":
    sys.exit(main())
