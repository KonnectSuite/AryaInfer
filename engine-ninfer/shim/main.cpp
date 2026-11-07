// AryaInfer's NInfer backend: a line-protocol shim over the pinned roofkid/ninfer-4080 engine.
//
// AryaInfer's Python server renders the chat template, applies the thinking budget and parses the
// model's tokens itself; the engine only has to turn prompt ids into generated ids. This program
// therefore speaks the StrataEngine protocol (READY / INFO / GEN / T / PP / RESUME / DONE / ERR,
// STOP, QUIT, VRAM) and leaves every template and sampling decision to the server, except the
// sampling keys the server sends on the GEN line.
//
// Protocol reference: AryaInfer serve/server.py StrataEngine.generate() and _parse_done().

#include <ninfer/engine.h>
#include <ninfer/types.h>

#include <atomic>
#include <chrono>
#include <condition_variable>
#include <cstdarg>
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <deque>
#include <fstream>
#include <iostream>
#include <memory>
#include <mutex>
#include <optional>
#include <sstream>
#include <string>
#include <string_view>
#include <thread>
#include <vector>

namespace {

using ninfer::Engine;
using ninfer::EngineOptions;
using ninfer::ExternalVisionItem;
using ninfer::GenerationResult;
using ninfer::KvCacheStorage;
using ninfer::OutputDelta;
using ninfer::OutputSink;
using ninfer::ProposalHead;
using ninfer::RequestOptions;
using ninfer::SpeculativeBackend;
using ninfer::TokenBatch;
using ninfer::TokenId;

struct Options {
    std::string artifact;
    std::uint32_t max_context    = 131072;
    std::uint32_t prefill_chunk  = 2688;
    std::uint32_t draft_tokens   = 3;
    std::uint32_t host_kv_mib    = 4096;
    int device                   = 0;
    KvCacheStorage kv            = KvCacheStorage::RK4V4E8;
    SpeculativeBackend spec      = SpeculativeBackend::Mtp;
    ProposalHead head            = ProposalHead::Optimized;
    bool use_graphs              = true;
    bool vision                  = false;
};

struct Request {
    int max_new = 0;
    std::vector<TokenId> ids;
    RequestOptions options;
    std::vector<ExternalVisionItem> vision;
    TokenId image_pad = -1;
};

std::mutex g_mutex;
std::condition_variable g_cv;
std::deque<Request> g_requests;
std::atomic<bool> g_cancel{false};
std::atomic<bool> g_quit{false};

void say(const char* fmt, ...) {
    va_list args;
    va_start(args, fmt);
    std::vprintf(fmt, args);
    va_end(args);
    std::fflush(stdout);
}

void note(const std::string& text) { std::fprintf(stderr, "[ninfer-engine] %s\n", text.c_str()); }

std::optional<KvCacheStorage> parse_kv(std::string_view name) {
    if (name == "bf16") { return KvCacheStorage::BFloat16; }
    if (name == "int8") { return KvCacheStorage::Int8Group64; }
    if (name == "rk4v4") { return KvCacheStorage::RotatedInt4KeyInt4ValueGroup64; }
    if (name == "rk4v4-e8") { return KvCacheStorage::RK4V4E8; }
    if (name == "rk2v4-e8") { return KvCacheStorage::RK2V4E8; }
    if (name == "fp8") { return KvCacheStorage::Fp8E4M3Row256; }
    if (name == "nvfp4") { return KvCacheStorage::Nvfp4Group16; }
    if (name == "k8v4") { return KvCacheStorage::Int8Group64; }
    return std::nullopt;
}

std::optional<SpeculativeBackend> parse_spec(std::string_view name) {
    if (name == "none" || name == "off") { return SpeculativeBackend::None; }
    if (name == "mtp") { return SpeculativeBackend::Mtp; }
    if (name == "dflash") { return SpeculativeBackend::DFlash; }
    if (name == "dflash2") { return SpeculativeBackend::DFlash2; }
    return std::nullopt;
}

std::string take_value(const std::vector<std::string>& args, std::size_t& i) {
    if (i + 1 >= args.size()) { throw std::invalid_argument("missing value after " + args[i]); }
    return args[++i];
}

Options parse_args(int argc, char** argv) {
    std::vector<std::string> args(argv + 1, argv + argc);
    Options out;
    for (std::size_t i = 0; i < args.size(); ++i) {
        const std::string& arg = args[i];
        if (arg == "--serve") { continue; }
        if (arg == "--artifact" || arg == "--model" || arg == "--weights") {
            out.artifact = take_value(args, i);
        } else if (arg == "--max-context" || arg == "--ctx") {
            out.max_context = static_cast<std::uint32_t>(std::stoul(take_value(args, i)));
        } else if (arg == "--prefill-chunk") {
            out.prefill_chunk = static_cast<std::uint32_t>(std::stoul(take_value(args, i)));
        } else if (arg == "--draft-tokens") {
            out.draft_tokens = static_cast<std::uint32_t>(std::stoul(take_value(args, i)));
        } else if (arg == "--host-kv-mib") {
            out.host_kv_mib = static_cast<std::uint32_t>(std::stoul(take_value(args, i)));
        } else if (arg == "--device") {
            out.device = std::stoi(take_value(args, i));
        } else if (arg == "--kv-dtype" || arg == "--kv") {
            const std::string value = take_value(args, i);
            const auto parsed       = parse_kv(value);
            if (!parsed) { throw std::invalid_argument("unknown --kv-dtype " + value); }
            out.kv = *parsed;
        } else if (arg == "--spec") {
            const std::string value = take_value(args, i);
            const auto parsed       = parse_spec(value);
            if (!parsed) { throw std::invalid_argument("unknown --spec " + value); }
            out.spec = *parsed;
        } else if (arg == "--lm-head-draft") {
            out.head = ProposalHead::Optimized;
        } else if (arg == "--no-cuda-graph") {
            out.use_graphs = false;
        } else if (arg == "--vision") {
            // The server adds this when the config has a vision section; the shim takes the
            // encoder's .sve rows through GENI, so it only has to reserve vision capacity.
            out.vision = true;
        } else if (arg == "--max-concurrency" || arg == "--ngram" || arg == "--ngram-max" ||
                   arg == "--ngram-n" || arg == "--ngram-min" || arg == "--ngram-pool-mib" ||
                   arg == "--log-level" || arg == "--vram-reserve-mib" || arg == "--prompt-batch" ||
                   arg == "--safety-margin-mib") {
            // Accepted and ignored: server-side knobs that do not apply to this engine.
            if (arg == "--ngram") {
                const std::string value = take_value(args, i);
                (void)value;   // n-gram drafts are disabled below; see the note at startup.
            } else if (arg != "--max-concurrency") {
                (void)take_value(args, i);
            }
        } else if (arg.rfind("--", 0) == 0) {
            note("ignoring unknown option " + arg);
        }
    }
    if (out.artifact.empty()) { throw std::invalid_argument("--artifact is required"); }
    return out;
}

class TokenSink final : public OutputSink {
public:
    void start(ninfer::GenerationStart start) override {
        reused_ = start.reused_prompt_tokens;
        if (reused_ > 0) { say("RESUME %u\n", reused_); }
    }
    void progress(ninfer::PromptProgress progress) override {
        const double ms   = static_cast<double>(progress.elapsed_ns) / 1.0e6;
        const double rate = progress.elapsed_ns == 0
                                ? 0.0
                                : static_cast<double>(progress.processed_prompt_tokens) /
                                      (static_cast<double>(progress.elapsed_ns) / 1.0e9);
        say("PP %u %u %.1f %.1f\n", progress.processed_prompt_tokens,
            progress.total_prompt_tokens, ms, rate);
    }
    void timing(ninfer::GenerationTimingObservation) override {}
    void publish(OutputDelta) override {}
    void tokens(TokenBatch batch) override {
        for (const TokenId id : batch.token_ids) { say("T %u\n", static_cast<unsigned>(id)); }
    }
    [[nodiscard]] std::uint32_t reused() const noexcept { return reused_; }

private:
    std::uint32_t reused_ = 0;
};

const char* finish_name(ninfer::FinishReason reason) {
    using ninfer::FinishReason;
    switch (reason) {
    case FinishReason::StopToken:
    case FinishReason::StopString: return "stop";
    case FinishReason::OutputLimit:
    case FinishReason::ContextCapacity: return "length";
    case FinishReason::Cancelled: return "cancel";
    default: return "stop";
    }
}

void print_done(const GenerationResult& result, std::size_t prompt_tokens) {
    const double prompt_ms = result.timings.prefill_seconds * 1000.0;
    const double decode_ms = result.timings.decode_seconds * 1000.0;
    say("DONE %zu %zu %.1f %.1f %s %llu %llu %u 0 0\n", result.generated_token_ids.size(),
        prompt_tokens, prompt_ms, decode_ms, finish_name(result.finish_reason),
        static_cast<unsigned long long>(result.speculative.accepted_tokens),
        static_cast<unsigned long long>(result.speculative.drafted_tokens),
        result.reused_prompt_tokens);
}

std::uint16_t bf16_of(float value) {
    std::uint32_t bits = 0;
    std::memcpy(&bits, &value, sizeof bits);
    bits += 0x7FFFU + ((bits >> 16U) & 1U);
    return static_cast<std::uint16_t>(bits >> 16U);
}

// One .sve file holds one record per image: int32 header (magic "SVE1", rows, nx, lines,
// n_embd), then rows * n_embd float32 values.  The server's strata-vision encoder writes it.
std::vector<ExternalVisionItem> load_sve(const std::string& path) {
    std::ifstream in(path, std::ios::binary);
    if (!in) { throw std::invalid_argument("cannot open vision embeddings: " + path); }
    std::vector<ExternalVisionItem> items;
    for (;;) {
        std::int32_t hdr[5] = {};
        in.read(reinterpret_cast<char*>(hdr), sizeof hdr);
        if (in.gcount() == 0) { break; }
        if (in.gcount() != static_cast<std::streamsize>(sizeof hdr) ||
            hdr[0] != 0x31455653 || hdr[1] <= 0 || hdr[2] <= 0 || hdr[3] <= 0 || hdr[4] <= 0 ||
            static_cast<std::int64_t>(hdr[2]) * hdr[3] != hdr[1]) {
            throw std::invalid_argument("vision embeddings file has an invalid record: " + path);
        }
        ExternalVisionItem item;
        item.rows    = static_cast<std::uint32_t>(hdr[1]);
        item.nx      = static_cast<std::uint32_t>(hdr[2]);
        item.lines   = static_cast<std::uint32_t>(hdr[3]);
        item.columns = static_cast<std::uint32_t>(hdr[4]);
        const std::size_t row_elements = static_cast<std::size_t>(item.columns);
        item.embeddings_bf16.resize(static_cast<std::size_t>(item.rows) * row_elements);
        std::vector<float> row(row_elements);
        for (std::uint32_t r = 0; r < item.rows; ++r) {
            in.read(reinterpret_cast<char*>(row.data()),
                    static_cast<std::streamsize>(row_elements * sizeof(float)));
            if (!in) { throw std::invalid_argument("vision embeddings file is truncated: " + path); }
            for (std::size_t c = 0; c < row_elements; ++c) {
                item.embeddings_bf16[static_cast<std::size_t>(r) * row_elements + c] =
                    bf16_of(row[c]);
            }
        }
        items.push_back(std::move(item));
    }
    if (items.empty()) { throw std::invalid_argument("vision embeddings file has no records: " + path); }
    return items;
}

Request parse_request(const std::string& line) {
    std::istringstream stream(line);
    std::vector<std::string> fields;
    std::string field;
    while (stream >> field) { fields.push_back(field); }
    if (fields.size() < 3) { throw std::invalid_argument("GEN needs a token budget and a prompt"); }
    const bool with_vision = fields[0] == "GENI";
    if (!with_vision && fields[0] != "GEN") {
        throw std::invalid_argument("only GEN and GENI are supported");
    }
    if (with_vision && fields.size() < 4) {
        throw std::invalid_argument("GENI needs an embeddings file and a prompt");
    }

    Request request;
    request.max_new = std::stoi(fields[1]);
    if (request.max_new <= 0) { throw std::invalid_argument("GEN token budget must be positive"); }

    request.options.execution.requested_output_tokens = static_cast<std::uint32_t>(request.max_new);
    request.options.execution.allow_prefix_reuse      = true;
    request.options.stop.include_model_defaults       = true;
    request.options.output.preserve_special_tokens    = true;

    const std::size_t key_end = with_vision ? fields.size() - 2 : fields.size() - 1;
    for (std::size_t i = 2; i < key_end; ++i) {
        const std::string& key_value = fields[i];
        const std::size_t eq         = key_value.find('=');
        if (eq == std::string::npos) { continue; }
        const std::string key   = key_value.substr(0, eq);
        const std::string value = key_value.substr(eq + 1);
        auto& sampling          = request.options.execution.sampling;
        if (key == "temperature") {
            sampling.temperature = std::stof(value);
        } else if (key == "top_p") {
            sampling.top_p = std::stof(value);
        } else if (key == "top_k") {
            sampling.top_k = std::stoi(value);
        } else if (key == "min_p") {
            sampling.min_p = std::stof(value);
        } else if (key == "penalty_present") {
            sampling.presence_penalty = std::stof(value);
        } else if (key == "penalty_freq") {
            sampling.frequency_penalty = std::stof(value);
        } else if (key == "seed") {
            sampling.seed = std::stoull(value);
        } else if (key == "image_pad") {
            request.image_pad = static_cast<TokenId>(std::stoi(value));
        } else if (key == "penalty_repeat" || key == "penalty_last_n" || key == "turn_at" ||
                   key == "pin" || key == "ckpt" || key == "cvec" || key == "pipe" ||
                   key == "pcie_frac" || key == "spec_min_p" || key == "aux_cpus" ||
                   key == "img_keys") {
            // AryaInfer/strata keys with no NInfer equivalent (or handled by the server). The
            // presence penalty arrives as penalty_present; repetition penalties are not modelled.
        } else {
            note("ignoring GEN key " + key);
        }
    }

    const std::string& ids = fields.back();
    std::size_t begin      = 0;
    while (begin <= ids.size()) {
        const std::size_t end = ids.find(',', begin);
        const std::string_view part =
            std::string_view(ids).substr(begin, end == std::string::npos ? std::string::npos : end - begin);
        if (!part.empty()) {
            request.ids.push_back(static_cast<TokenId>(std::stoul(std::string(part))));
        }
        if (end == std::string::npos) { break; }
        begin = end + 1;
    }
    if (request.ids.empty()) { throw std::invalid_argument("GEN carries no prompt tokens"); }
    if (with_vision) {
        if (request.image_pad < 0) { throw std::invalid_argument("GENI carries no image_pad id"); }
        request.vision = load_sve(fields[fields.size() - 2]);
        request.options.execution.allow_prefix_reuse = false;   // picture state is not in the token ids
    }
    return request;
}

void reader_loop() {
    std::string line;
    while (std::getline(std::cin, line)) {
        if (!line.empty() && line.back() == '\r') { line.pop_back(); }
        if (line == "STOP") {
            g_cancel.store(true);
            continue;
        }
        if (line == "QUIT") {
            g_quit.store(true);
            g_cancel.store(true);
            g_cv.notify_all();
            return;
        }
        if (line == "VRAM" || line.rfind("VRAM ", 0) == 0) {
            // The server asks only for diagnostics; report no elastic expert cache.
            say("VRAM expert_slots=0 expert_cache_mib=0\n");
            continue;
        }
        if (line.rfind("GEN ", 0) == 0 || line.rfind("GENI ", 0) == 0) {
            try {
                Request request = parse_request(line);
                {
                    std::lock_guard lock(g_mutex);
                    g_requests.push_back(std::move(request));
                }
                g_cv.notify_all();
            } catch (const std::exception& error) {
                say("ERR %s\n", error.what());
            }
            continue;
        }
        if (line.empty()) { continue; }
        note("ignoring command " + line);
    }
    g_quit.store(true);
    g_cv.notify_all();
}

}  // namespace

int main(int argc, char** argv) {
    Options options;
    try {
        options = parse_args(argc, argv);
    } catch (const std::exception& error) {
        std::fprintf(stderr, "[ninfer-engine] %s\n", error.what());
        return 2;
    }

    EngineOptions engine_options;
    engine_options.artifact_path        = options.artifact;
    engine_options.device               = options.device;
    engine_options.max_context          = options.max_context;
    engine_options.kv_capacity          = ninfer::KvCapacityPolicy::explicit_capacity(options.max_context);
    engine_options.max_concurrency      = 1;
    engine_options.max_pending_requests = 4;
    engine_options.prefill_chunk        = options.prefill_chunk;
    engine_options.kv_cache             = options.kv;
    engine_options.speculative.backend  = options.spec;
    engine_options.speculative.draft_tokens = options.spec == SpeculativeBackend::None ? 0 : options.draft_tokens;
    engine_options.speculative.proposal_head = options.head;
    engine_options.speculative.ngram.mode    = ninfer::NgramDraftMode::Off;
    engine_options.use_cuda_graph            = options.use_graphs;
    engine_options.enable_vision             = options.vision;
    engine_options.vision_max_tokens         = 1024;   // the server's encoder is pinned to 1024 tokens
    engine_options.context_cache.enabled     = true;
    engine_options.context_cache.host_state_slots     = 8;
    engine_options.context_cache.device_state_slots   = 2;
    engine_options.context_cache.max_private_continuations = 4;
    engine_options.context_cache.max_shared_prefixes      = 4;
    engine_options.context_cache.max_long_anchors_per_continuation = 2;
    engine_options.context_cache.host_kv_capacity_bytes =
        static_cast<std::size_t>(options.host_kv_mib) << 20U;

    std::unique_ptr<Engine> engine;
    try {
        engine = std::make_unique<Engine>(engine_options);
    } catch (const std::exception& error) {
        std::fprintf(stderr, "[ninfer-engine] engine did not start: %s\n", error.what());
        return 1;
    }

    say("INFO model=qwen3.8-27b\n");
    say("INFO weights=gsq3\n");
    say("INFO engine=ninfer-4080\n");
    say("READY %u stop\n", options.max_context);
    std::fflush(stdout);

    std::thread reader(reader_loop);
    reader.detach();

    for (;;) {
        Request request;
        {
            std::unique_lock lock(g_mutex);
            g_cv.wait(lock, [] { return g_quit.load() || !g_requests.empty(); });
            if (g_requests.empty()) { break; }
            request = std::move(g_requests.front());
            g_requests.pop_front();
        }
        g_cancel.store(false);

        const std::size_t prompt_tokens = request.ids.size();
        try {
            auto prepared = request.vision.empty()
                                ? engine->prepare_tokens(std::move(request.ids))
                                : engine->prepare_tokens_with_vision(
                                      std::move(request.ids), std::move(request.vision),
                                      request.image_pad);
            auto handle   = engine->submit(
                std::move(prepared), std::move(request.options), ninfer::OutputConsumerMode::Streaming,
                ninfer::GenerationObservationOptions{
                    .phase_timings = true, .live_timings = true, .prompt_progress = true});
            TokenSink sink;
            GenerationResult result =
                handle.wait(&sink, ninfer::CancellationView([] { return g_cancel.load(); }));
            print_done(result, prompt_tokens);
            if (std::getenv("NINFER_DEBUG_CACHE")) {
            const ninfer::RuntimeStats stats   = engine->runtime_stats();
            const ninfer::MemorySummary memory = engine->memory_summary();
            std::cerr << "[shim] root=" << stats.root_selections
                      << " endpoint=" << stats.private_endpoint_selections
                      << " anchor=" << stats.private_long_anchor_selections
                      << " shared=" << stats.shared_stable_prefix_selections
                      << " reused=" << stats.reused_prompt_tokens
                      << " frontier=" << stats.last_selected_frontier_tokens
                      << " computed=" << stats.computed_prefill_tokens << " host="
                      << memory.host_state_occupied_slots << "/"
                      << memory.host_state_capacity_slots << '\n';
            }
        } catch (const std::exception& error) {
            say("ERR %s\n", error.what());
        }
        if (g_quit.load()) { break; }
    }
    return 0;
}
