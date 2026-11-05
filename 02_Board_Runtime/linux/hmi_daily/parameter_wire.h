#ifndef CABINET_PARAMETER_WIRE_H
#define CABINET_PARAMETER_WIRE_H
#include <sys/socket.h>
#include <sys/un.h>
#include <sys/stat.h>
#include <unistd.h>
#include <fcntl.h>
#include <poll.h>
#include <errno.h>
#include <limits.h>
#include <stdlib.h>
#include <string.h>
#include <stdio.h>
#include <time.h>

typedef struct {
    char call_id[33], state[64], context[65], request_id[33], nonce[33], last_state[64];
    int enabled, revision, current, minimum, maximum;
} parameter_reply_t;

static int parameter_hex(const char *text, size_t length) {
    if(strlen(text) != length) return 0;
    for(size_t index = 0; index < length; index++) if(!((text[index] >= '0' && text[index] <= '9') || (text[index] >= 'a' && text[index] <= 'f'))) return 0;
    return 1;
}

static int parameter_integer(const char *text, int *result) {
    char *end; errno = 0;
    long parsed = strtol(text, &end, 10);
    if(!*text || *end || errno || parsed < INT_MIN || parsed > INT_MAX) return 0;
    *result = (int)parsed; return 1;
}

static int parameter_state(const char *text) {
    const char *allowed[] = {"NONE", "STATUS", "PREVIEW_NOT_APPLIED", "QUEUED_NOT_APPLIED", "APPLIED_PS_SETPOINT_NOT_PL_OUTPUT_CONFIRMATION", "REJECTED_NOT_APPLIED"};
    for(size_t index = 0; index < sizeof(allowed) / sizeof(allowed[0]); index++) if(strcmp(text, allowed[index]) == 0) return 1;
    return 0;
}

static int parameter_parse(char *text, const char *expected, parameter_reply_t *result) {
    const char *keys[] = {"schema", "call_id", "state", "enabled", "revision", "current_tenths", "minimum_tenths", "maximum_tenths", "context_token", "request_id", "nonce", "last_state"};
    unsigned seen = 0; char *position = NULL;
    memset(result, 0, sizeof(*result));
    for(char *line = strtok_r(text, "\n", &position); line; line = strtok_r(NULL, "\n", &position)) {
        char *separator = strchr(line, '\t');
        if(!separator || strchr(separator + 1, '\t')) return 0;
        *separator++ = 0;
        size_t field;
        for(field = 0; field < 12 && strcmp(line, keys[field]); field++);
        if(field == 12 || (seen & (1u << field))) return 0;
        seen |= 1u << field;
        if(field == 0 && strcmp(separator, "parameter-local-v1")) return 0;
        if(field == 1) { if(!parameter_hex(separator, 32) || strcmp(separator, expected)) return 0; memcpy(result->call_id, separator, 33); }
        if(field == 2 || field == 11) {
            if(!parameter_state(separator)) return 0;
            snprintf(field == 2 ? result->state : result->last_state, 64, "%s", separator);
        }
        int *numbers[] = {&result->enabled, &result->revision, &result->current, &result->minimum, &result->maximum};
        if(field >= 3 && field <= 7 && !parameter_integer(separator, numbers[field - 3])) return 0;
        if(field == 8) { if(!parameter_hex(separator, 64)) return 0; memcpy(result->context, separator, 65); }
        if(field == 9 || field == 10) {
            if(strcmp(separator, "-") && !parameter_hex(separator, 32)) return 0;
            snprintf(field == 9 ? result->request_id : result->nonce, 33, "%s", separator);
        }
    }
    if(seen != 4095 || result->revision < 0 || (result->enabled != 0 && result->enabled != 1)) return 0;
    if(result->enabled && (result->minimum < -550 || result->maximum > 1250 || result->minimum > result->maximum || result->current < -550 || result->current > 1250)) return 0;
    if(strcmp(result->state, "PREVIEW_NOT_APPLIED") == 0 && (!parameter_hex(result->nonce, 32) || !parameter_hex(result->request_id, 32))) return 0;
    return 1;
}

static unsigned long long parameter_now(void) {
    struct timespec stamp; clock_gettime(CLOCK_MONOTONIC, &stamp);
    return (unsigned long long)stamp.tv_sec * 1000 + (unsigned long long)stamp.tv_nsec / 1000000;
}

static int parameter_wait(int descriptor, short events, unsigned long long deadline) {
    for(;;) {
        unsigned long long now = parameter_now(); if(now >= deadline) return 0;
        struct pollfd item = {descriptor, events, 0};
        int result = poll(&item, 1, (int)(deadline - now));
        if(result < 0 && errno == EINTR) continue;
        return result > 0 && (item.revents & events);
    }
}

static int parameter_exchange(const char *path, const char *request, const char *identity, parameter_reply_t *reply) {
    struct sockaddr_un address; struct stat info;
    if(!path || strlen(path) >= sizeof(address.sun_path) || strlen(request) > 2048 || !parameter_hex(identity, 32) ||
       lstat(path, &info) || !S_ISSOCK(info.st_mode) || info.st_uid != geteuid() || (info.st_mode & 077)) return 0;
    int descriptor = socket(AF_UNIX, SOCK_STREAM, 0); if(descriptor < 0) return 0;
    fcntl(descriptor, F_SETFD, FD_CLOEXEC);
#ifdef SO_NOSIGPIPE
    int no_signal = 1; setsockopt(descriptor, SOL_SOCKET, SO_NOSIGPIPE, &no_signal, sizeof(no_signal));
#endif
    int flags = fcntl(descriptor, F_GETFL, 0), success = 0;
    unsigned long long deadline = parameter_now() + 1200;
    if(flags < 0 || fcntl(descriptor, F_SETFL, flags | O_NONBLOCK) < 0) goto done;
    memset(&address, 0, sizeof(address)); address.sun_family = AF_UNIX; memcpy(address.sun_path, path, strlen(path) + 1);
    if(connect(descriptor, (struct sockaddr *)&address, sizeof(address)) < 0) {
        if(errno != EINPROGRESS || !parameter_wait(descriptor, POLLOUT, deadline)) goto done;
        int failure = 0; socklen_t length = sizeof(failure);
        if(getsockopt(descriptor, SOL_SOCKET, SO_ERROR, &failure, &length) || failure) goto done;
    }
#ifdef __APPLE__
    uid_t peer; gid_t group; if(getpeereid(descriptor, &peer, &group) || peer != geteuid()) goto done;
#elif defined(__linux__)
    struct { pid_t pid; uid_t uid; gid_t gid; } peer;
    socklen_t peer_length = sizeof(peer);
    if(getsockopt(descriptor, SOL_SOCKET, SO_PEERCRED, &peer, &peer_length) || peer_length != sizeof(peer) || peer.uid != geteuid()) goto done;
#else
    goto done;
#endif
    size_t sent = 0, total = strlen(request);
    while(sent < total) {
        if(!parameter_wait(descriptor, POLLOUT, deadline)) goto done;
#ifdef MSG_NOSIGNAL
        ssize_t count = send(descriptor, request + sent, total - sent, MSG_NOSIGNAL);
#else
        ssize_t count = send(descriptor, request + sent, total - sent, 0);
#endif
        if(count < 0 && (errno == EAGAIN || errno == EINTR)) continue;
        if(count <= 0) goto done;
        sent += (size_t)count;
    }
    char response[4097]; size_t used = 0;
    while(used < sizeof(response) - 1) {
        if(!parameter_wait(descriptor, POLLIN, deadline)) goto done;
        ssize_t count = recv(descriptor, response + used, sizeof(response) - 1 - used, 0);
        if(count < 0 && (errno == EAGAIN || errno == EINTR)) continue;
        if(count <= 0) goto done;
        used += (size_t)count; response[used] = 0;
        if(memchr(response, 0, used)) goto done;
        char *end = strstr(response, "\n\n");
        if(end) { if(end[2]) goto done; success = parameter_parse(response, identity, reply); break; }
    }
done:
    close(descriptor); return success;
}
#endif
