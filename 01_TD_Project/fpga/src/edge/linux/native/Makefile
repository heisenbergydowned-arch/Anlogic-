CC ?= cc
CFLAGS ?= -O2 -std=c11 -Wall -Wextra -Werror

all: libedge_mmio.so

libedge_mmio.so: mmio.c
	$(CC) $(CFLAGS) -shared -fPIC -o $@ $<

clean:
	rm -f libedge_mmio.so

.PHONY: all clean
