// src/poly/guesses.hpp - a round's guesses from the draft block: whether it is asked, and how many join the window.
//
// A round feeds the token the model wrote and, when they pay, guesses at what follows it (Engine::window).  The
// block guesses, each guess from the one before.  A guess joins the window while the window is then expected to
// write more tokens a millisecond.  The chance that the guesses up to it are all right is the product of the
// block's own, and what a token more costs is what the rounds so far have measured: what a round takes, by the
// tokens of its window, and what asking the block takes.
//
// A length the rule gives up is not run, and a block that is not asked takes no time, so a time that once stopped
// the guesses was never measured again: one slow stretch ended the guessing for the rest of an answer.  The
// stretch can be a busy machine, or the first answer after a start, when the model's pages still come from the
// disk.  So a time older than kFresh rounds is not believed.  Until its length is run again a token more counts
// as the policy counts one it has not seen, and asking as free, and the time measured then stands as it is.  A
// round among fresh ones counts for twice the time before it at most, so one stall moves a time by a tenth.
//
// measure_widths(true) switches the width to what the rounds measured (EAGLE-4's chain rule): a window of w tokens
// is expected to write 1 + A_0 + ... + A_{w-2} tokens, where A_d is the chance that the guesses through position d
// are all right - the rounds' own count once they have measured it, the block's probability until they have - and
// the window chosen is the one whose expected tokens a round's measured time is greatest.  Off by default.
//
// Nothing here knows the model or the engine.
#pragma once

#include "strata/spec/draft_policy.hpp"

#include <algorithm>

namespace strata::poly {

// Whether asking the block pays at all.  A guess costs a run of the block before it is known to be worth a
// window, and a window costs more the less its layers' matrices like several tokens at once, so with some
// models, or with most experts on the CPU, an answer is written faster without the block.  The tokens a
// millisecond of the rounds that asked it and of the rounds that did not are compared, and the side that is
// behind still gets a round now and then, so that it stays measured; its few rounds each count for more, so
// that both sides remember about as long a stretch of the answer.  How often depends on what the round
// costs.  The block behind is asked every 8th round: that costs little, and a stretch of text it guesses
// badly ends.  A round without the block costs the most where the block is far ahead: every 96th when it is
// more than a tenth ahead, else every 24th.  The block's first rounds are not counted: its windows are short
// until the policy has seen some.
struct Gate {
    double tokens[2] = {}, ms[2] = {};   // [asked]: sums that forget
    int seen[2] = {};
    long long rounds = 0;
    bool pays = true;

    bool ask() {
        ++rounds;
        if (seen[1] < 16) return true;
        if (seen[0] < 4) return false;
        const double with = tokens[1] * ms[0], without = tokens[0] * ms[1];   // the two rates, over one divisor
        pays = with >= without;
        return rounds % (!pays ? 8 : with > 1.1 * without ? 96 : 24) == 0 ? !pays : pays;
    }
    void saw(bool asked, int n, double round_ms) {
        if (++seen[asked] <= 8 && asked) return;
        const double keep = asked == pays ? 0.97 : 0.7;
        tokens[asked] = tokens[asked] * keep + n;
        ms[asked] = ms[asked] * keep + round_ms;
    }
};

class Guesses {
public:
    static constexpr int kFresh = 32;             ///< the rounds for which a time is believed
    /// A token more, of a token alone, where it is not measured: the step of the policy's shape (draft_policy.cpp).
    static constexpr double kUnmeasured = 0.35;
    /// The rounds the block's own probability stands in for at a guess position, before the measured rate takes over.
    static constexpr double kPrior = 8.0;

    Gate gate;

    /// The window's width from the measured acceptance instead of the block's own probabilities (opt-in).
    void measure_widths(bool on) { by_measure_ = on; }

    /// A round begins.  `blocks`: the block may be asked in it.  `limit`: the window the caller would allow.  Returns
    /// whether it is asked at all.
    bool begin(bool blocks, const spec::DraftPolicy& policy, int limit = spec::DraftPolicy::kMaxT) {
        ++round_;
        blocks_ = blocks;
        asked_ = 0;
        sure_ = tokens_ = 1.0;
        one_ = fresh(at_[1]) ? ms_[1] : policy.cost_ms(1);   // a token alone is the measure, old or not
        // the measured width must not price a token more off a stale cold round; the default path keeps its measure
        if (by_measure_ && knows(2) && ms_[2] > 0.0) one_ = std::min(one_, ms_[2]);
        limit_ = std::clamp(limit, 1, spec::DraftPolicy::kMaxT);
        width_ = by_measure_ ? choose_width() : limit_;
        // a probe now and then, so a width that fell to no guess can widen again on what the block says now
        if (by_measure_ && width_ <= 1 && round_ % 32 == 0) width_ = 2;
        return blocks && width_ > 1 && gate.ask();
    }

    /// Whether the block is asked for a guess more, the window having n of them.
    bool wants(int n) {
        if (by_measure_) return n + 2 <= width_;
        const int to = n + 2;   // the window's tokens with this guess
        more_ = knows(to) ? std::clamp((ms_[to] - round_ms(to - 1)) / one_, 0.2, 0.8) : kUnmeasured;
        // asking takes time too: not when a guess the block were sure of would not pay for it
        const double ask = measured_ && fresh(asked_at_) ? ask_ms_ : 0.0;
        return sure_ * round_ms(to - 1) > tokens_ * (more_ * one_ + ask);
    }

    /// The block's guess after n others, right with probability p; asking took `ms`.  Returns whether it joins
    /// the window.
    bool takes(int n, double p, double ms) {
        prior_[n] = (n == 0 ? 1.0 : prior_[n - 1]) * std::clamp(p, 0.0, 1.0);
        ask_ms_ = fresh(asked_at_) ? ask_ms_ + 0.1 * (std::min(ms, 2.0 * ask_ms_) - ask_ms_) : ms;
        asked_at_ = round_;
        ++asked_;
        if (by_measure_) return n + 2 <= width_;
        sure_ *= p;
        if (sure_ * round_ms(n + 1) <= tokens_ * more_ * one_) return false;
        tokens_ += sure_;
        return true;
    }

    /// The round is over: a window of t tokens wrote `wrote` of them in `ms`.  Returns the time as it counts,
    /// which is the policy's too: none for a round that recorded launches, which took many rounds' time.
    double end(int t, int wrote, double ms, bool recorded) {
        if (recorded) return 0.0;
        t = std::clamp(t, 1, spec::DraftPolicy::kMaxT);
        for (int j = 0; j < t - 1; ++j) {   // per guess position: drafted there, accepted there
            ++drafted_[j];
            if (j < wrote - 1) ++accepted_[j];
        }
        if (knows(t)) ms = std::min(ms, 2.0 * ms_[t]);
        ms_[t] = knows(t) ? ms_[t] + 0.1 * (ms - ms_[t]) : ms;
        at_[t] = round_;
        measured_ = true;
        if (blocks_) gate.saw(asked_ > 0, wrote, ms);
        return ms;
    }

private:
    bool fresh(long long at) const { return at && round_ - at <= kFresh; }
    bool knows(int t) const { return fresh(at_[t]); }
    // what a round with a window of t tokens takes: as measured, or a token more than the next shorter one
    double round_ms(int t) const { return t <= 1 ? one_ : knows(t) ? ms_[t] : round_ms(t - 1) + kUnmeasured * one_; }
    // P(the guesses through position d are all right): what the rounds measured, with the position before it (or the
    // block's own probability, at the first) standing in for the rounds not measured yet.
    double acceptance(int d) const {
        double base = prior_[d];
        if (d > 0) {
            const double below = measured_rate(d - 1);
            if (below > 0.0) base = below;
        }
        const double rate = (double(accepted_[d]) + kPrior * base) / (double(drafted_[d]) + kPrior);
        return std::clamp(rate, 0.0, 1.0);
    }
    // What the rounds measured at a position: the accepted of the drafted, smoothed; 0 before any was drafted there.
    double measured_rate(int d) const {
        return drafted_[d] > 0 ? (double(accepted_[d]) + 1.0) / (double(drafted_[d]) + 2.0) : 0.0;
    }
    // The window whose expected tokens a round's time is greatest; a window of 1 token (no guess) competes with them.
    // Every 16th round the choice goes one deeper, so a depth the rule would not choose is measured now and then.
    int choose_width() const {
        int best = 1;
        double best_rate = round_ms(1) > 0.0 ? 1.0 / round_ms(1) : 0.0;
        double a = 1.0, gain = 1.0;
        for (int w = 2; w <= limit_; ++w) {
            a *= acceptance(w - 2);
            gain += a;
            const double cost = round_ms(w);
            const double rate = cost > 0.0 ? gain / cost : 0.0;
            if (rate > best_rate) {
                best_rate = rate;
                best = w;
            }
        }
        if (by_measure_ && round_ % 16 == 0 && best < limit_) ++best;
        return best;
    }

    long long round_ = 0;                            // the first is 1
    double ms_[spec::DraftPolicy::kMaxT + 1] = {};   // a round's time by its window's tokens
    long long at_[spec::DraftPolicy::kMaxT + 1] = {};   // the round that time is of; 0: none yet
    double ask_ms_ = 0.0;                            // what one guess of the block takes
    long long asked_at_ = 0;
    bool measured_ = false;                          // some round's time is known: asking can be weighed against it
    bool by_measure_ = false;                        // the width from the measured acceptance (measure_widths)
    int limit_ = spec::DraftPolicy::kMaxT;
    int width_ = 1;
    // per guess position: the rounds that drafted it, the rounds that accepted it, and the block's own probability
    // through it (the prior the measured rate replaces)
    long long drafted_[spec::DraftPolicy::kMaxT] = {};
    long long accepted_[spec::DraftPolicy::kMaxT] = {};
    double prior_[spec::DraftPolicy::kMaxT] = {0.8, 0.64, 0.512, 0.41, 0.328, 0.262, 0.21, 0.168};
    // of the round
    bool blocks_ = false;
    int asked_ = 0;
    double one_ = 1.0, more_ = kUnmeasured, sure_ = 1.0, tokens_ = 1.0;
};

}  // namespace strata::poly
