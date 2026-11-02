// Isolated, one-session diagnostic collector. Never load in a live worker.
// The caller must synchronize CUDA before finish and must not use Kineto.
#include <cupti.h>
#include <dlfcn.h>
#include <fcntl.h>
#include <unistd.h>
#include <cstdlib>
#include <cstdio>
#include <cstring>
#include <map>
#include <mutex>
#include <set>
#include <string>

namespace {
std::mutex mutex;
int fd = -1;
int intervalsFd = -1;
unsigned long intervalSeq = 0;
bool started = false, flushing = false, failed = false;
unsigned long seq = 0, allocated = 0, completed = 0, queries = 0, kernels = 0;
std::map<uint8_t*, unsigned long> buffers;
std::set<std::pair<CUcontext, uint32_t>> contexts;
decltype(&cuptiActivityRegisterCallbacks) regCallbacks;
decltype(&cuptiActivityEnable) enableActivity;
decltype(&cuptiActivityDisable) disableActivity;
decltype(&cuptiActivityFlushAll) flushActivity;
decltype(&cuptiActivityGetNumDroppedRecords) droppedRecords;
decltype(&cuptiActivityGetNextRecord) nextRecord;

// Called with mutex held. A failed write leaves an invalid/incomplete transcript.
void emit(const std::string& fields) {
    std::string line = "{\"seq\":" + std::to_string(seq++) + "," + fields + "}\n";
    if (seq > 50000 || fd < 0 || write(fd, line.data(), line.size()) != (ssize_t)line.size()) failed = true;
}
void error(const char* code) {
    failed = true;
    emit(std::string("\"kind\":\"failure\",\"code\":\"") + code + "\"");
}
void interval(const std::string& fields) {
    std::string line = "{\"seq\":" + std::to_string(intervalSeq++) + "," + fields + "}\n";
    if (intervalSeq > 50000 || intervalsFd < 0 || write(intervalsFd, line.data(), line.size()) != (ssize_t)line.size()) error("interval_write_failed");
}
std::string binding(CUcontext context, uint32_t stream) {
    char buf[128];
    snprintf(buf, sizeof(buf), "\"context\":\"ctx-%llx\",\"stream\":%u",
             (unsigned long long)(uintptr_t)context, stream);
    return buf;
}
void CUPTIAPI requested(uint8_t** buffer, size_t* size, size_t* maxRecords) {
    std::lock_guard<std::mutex> lock(mutex);
    *buffer = nullptr; *size = 0; *maxRecords = 0;
    if (flushing || failed || buffers.size() >= 8 || allocated >= 10000) { error("buffer_refused"); return; }
    void* memory = nullptr;
    if (posix_memalign(&memory, 8, 1024*1024) != 0) { error("allocation_failed"); return; }
    *buffer = static_cast<uint8_t*>(memory); *size = 1024*1024;
    const auto id = ++allocated; buffers[*buffer] = id;
    emit("\"kind\":\"buffer_requested\",\"buffer\":\"allocation-" + std::to_string(id) + "\"");
}
void CUPTIAPI finished(CUcontext context, uint32_t stream, uint8_t* buffer, size_t size, size_t validSize) {
    unsigned long id;
    {
        std::lock_guard<std::mutex> lock(mutex);
        auto it = buffers.find(buffer);
        if (it == buffers.end()) { error("unknown_buffer"); return; }
        id = it->second;
    }
    // Never hold our mutex while re-entering CUPTI (callbacks may acquire it).
    bool parsed = validSize <= size;
    unsigned long count = 0, records = 0;
    CUpti_Activity* record = nullptr;
    while (parsed && validSize) {
        auto status = nextRecord(buffer, validSize, &record);
        if (status == CUPTI_ERROR_MAX_LIMIT_REACHED) break;
        if (status != CUPTI_SUCCESS || !record || ++records > 2000000) { parsed = false; break; }
        if (record->kind == CUPTI_ACTIVITY_KIND_CONCURRENT_KERNEL || record->kind == CUPTI_ACTIVITY_KIND_KERNEL) {
            const auto* kernel = reinterpret_cast<const CUpti_ActivityKernel9*>(record);
            std::lock_guard<std::mutex> lock(mutex);
            if (kernel->start == 0 || kernel->end <= kernel->start) { error("invalid_kernel_interval"); parsed = false; break; }
            ++count;
            interval("\"kind\":\"kernel\",\"buffer\":\"allocation-" + std::to_string(id) + "\",\"device\":" + std::to_string(kernel->deviceId) + ",\"stream\":" + std::to_string(kernel->streamId) + ",\"correlation\":" + std::to_string(kernel->correlationId) + ",\"start_ns\":" + std::to_string(kernel->start) + ",\"end_ns\":" + std::to_string(kernel->end));
        }
    }
    {
        std::lock_guard<std::mutex> lock(mutex);
        ++completed; kernels += count; contexts.insert({context, stream});
        emit("\"kind\":\"buffer_completed\",\"buffer\":\"allocation-" + std::to_string(id) + "\"," + binding(context, stream) + ",\"parse_status\":\"" + (parsed ? "ok" : "failed") + "\"");
        if (!parsed) failed = true;
    }
    size_t dropped = 0;
    auto status = droppedRecords(context, stream, &dropped);
    {
        std::lock_guard<std::mutex> lock(mutex);
        ++queries;
        emit("\"kind\":\"loss_check\",\"buffer\":\"allocation-" + std::to_string(id) + "\"," + binding(context, stream) + ",\"status\":" + std::to_string(status) + ",\"dropped\":" + std::to_string(dropped));
        if (status != CUPTI_SUCCESS || dropped) failed = true;
        buffers.erase(buffer);
    }
    free(buffer);
}
bool hex(const char* value, size_t length) {
    return value && strlen(value) == length && strspn(value, "0123456789abcdef") == length;
}
}

extern "C" int yerbas_collector_start(const char* library, const char* output, const char* run, const char* runtime, const char* recipe) {
    if (started || !hex(run, 32) || !hex(runtime, 64) || !hex(recipe, 64)) return 1;
    started = true;
    void* handle = dlopen(library, RTLD_NOW | RTLD_LOCAL);
    if (!handle) return 2;
#define LOAD(target, symbol) target = reinterpret_cast<decltype(target)>(dlsym(handle, #symbol)); if (!target) return 3
    LOAD(regCallbacks, cuptiActivityRegisterCallbacks);
    LOAD(enableActivity, cuptiActivityEnable);
    LOAD(disableActivity, cuptiActivityDisable);
    LOAD(flushActivity, cuptiActivityFlushAll);
    LOAD(droppedRecords, cuptiActivityGetNumDroppedRecords);
    LOAD(nextRecord, cuptiActivityGetNextRecord);
#undef LOAD
    fd = open(output, O_WRONLY | O_CREAT | O_EXCL | O_NOFOLLOW | O_CLOEXEC, 0600);
    if (fd < 0) return 4;
    intervalsFd = open((std::string(output) + ".kernels").c_str(), O_WRONLY | O_CREAT | O_EXCL | O_NOFOLLOW | O_CLOEXEC, 0600);
    if (intervalsFd < 0) { close(fd); fd = -1; return 4; }
    {
        std::lock_guard<std::mutex> lock(mutex);
        emit(std::string("\"kind\":\"start\",\"schema\":1,\"run_id\":\"") + run + "\",\"runtime_sha256\":\"" + runtime + "\",\"recipe_sha256\":\"" + recipe + "\"");
        interval(std::string("\"kind\":\"start\",\"schema\":1,\"run_id\":\"") + run + "\",\"runtime_sha256\":\"" + runtime + "\",\"recipe_sha256\":\"" + recipe + "\"");
    }
    auto status = regCallbacks(requested, finished);
    if (status == CUPTI_SUCCESS) status = enableActivity(CUPTI_ACTIVITY_KIND_CONCURRENT_KERNEL);
    if (status != CUPTI_SUCCESS) { std::lock_guard<std::mutex> lock(mutex); error("collector_setup_failed"); return 5; }
    return 0;
}

extern "C" int yerbas_collector_finish() {
    {
        std::lock_guard<std::mutex> lock(mutex);
        if (!started || fd < 0 || flushing) return 1;
        flushing = true;
        emit("\"kind\":\"flush_begin\"");
    }
    auto disable = disableActivity(CUPTI_ACTIVITY_KIND_CONCURRENT_KERNEL);
    auto flush = flushActivity(CUPTI_ACTIVITY_FLAG_FLUSH_FORCED);
    std::set<std::pair<CUcontext, uint32_t>> pending;
    {
        std::lock_guard<std::mutex> lock(mutex);
        if (disable != CUPTI_SUCCESS) error("disable_failed");
        emit("\"kind\":\"flush_end\",\"status\":" + std::to_string(flush));
        if (flush != CUPTI_SUCCESS || !buffers.empty() || completed == 0) failed = true;
        pending = contexts;
    }
    for (auto pair : pending) {
        size_t dropped = 0;
        auto status = droppedRecords(pair.first, pair.second, &dropped);
        std::lock_guard<std::mutex> lock(mutex);
        ++queries;
        emit("\"kind\":\"final_loss_check\"," + binding(pair.first, pair.second) + ",\"status\":" + std::to_string(status) + ",\"dropped\":" + std::to_string(dropped));
        if (status != CUPTI_SUCCESS || dropped) failed = true;
    }
    std::lock_guard<std::mutex> lock(mutex);
    interval("\"kind\":\"finish\",\"kernel_records\":" + std::to_string(kernels));
    if (fsync(intervalsFd) != 0) error("interval_sync_failed");
    close(intervalsFd); intervalsFd = -1;
    emit("\"kind\":\"finish\",\"buffers_requested\":" + std::to_string(allocated) + ",\"buffers_completed\":" + std::to_string(completed) + ",\"loss_queries\":" + std::to_string(queries));
    if (fsync(fd) != 0) failed = true;
    close(fd); fd = -1;
    return failed ? 6 : 0;
}
extern "C" unsigned long yerbas_collector_kernel_records() {
    std::lock_guard<std::mutex> lock(mutex);
    return kernels;
}
