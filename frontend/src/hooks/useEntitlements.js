import { useEffect, useState, useCallback } from "react";
import { getMySubscription } from "../services/subscriptionService";

// Subscription statuses that currently unlock the plan's paid features.
// Mirrors backend/app/models/subscription.py ACTIVE_STATUSES - kept here
// as the single frontend copy so every page computes "locked" the same
// way instead of trusting a possibly-stale plan flag on its own.
const ACTIVE_STATUSES = new Set(["active", "trialing"]);

const DEFAULT_STATE = {
  loading: true,
  error: null,
  planCode: null,
  planName: null,
  status: null,
  // hasFeature/hasAny are safe to call even while loading or on error -
  // they default to "locked" (false) rather than "unlocked", so a failed
  // fetch never accidentally unlocks a paid feature.
  features: {},
};

/**
 * Reads the calling company's ACTIVE plan entitlements from the existing
 * backend subscription endpoint (GET /subscription - the same source of
 * truth the backend's require_feature() dependency uses). This is the one
 * place the frontend decides "does this plan include feature X right now",
 * so individual pages never re-derive it from raw API responses (e.g. a
 * masked match_score of 0) or duplicate their own lock logic.
 */
export default function useEntitlements() {
  const [state, setState] = useState(DEFAULT_STATE);

  const load = useCallback(async () => {
    setState((s) => ({ ...s, loading: true, error: null }));
    try {
      const sub = await getMySubscription();
      const isActive = ACTIVE_STATUSES.has(sub?.status);
      const plan = sub?.plan || {};
      setState({
        loading: false,
        error: null,
        planCode: plan.code || null,
        planName: plan.name || null,
        status: sub?.status || null,
        features: {
          ai_resume_analysis_enabled: isActive && !!plan.ai_resume_analysis_enabled,
          ai_candidate_ranking_enabled: isActive && !!plan.ai_candidate_ranking_enabled,
          ai_recommendations_enabled: isActive && !!plan.ai_recommendations_enabled,
          ai_interview_questions_enabled: isActive && !!plan.ai_interview_questions_enabled,
          advanced_analytics_enabled: isActive && !!plan.advanced_analytics_enabled,
          multiple_recruiters_enabled: isActive && !!plan.multiple_recruiters_enabled,
        },
      });
    } catch (err) {
      // Fail closed: on error, every feature stays locked (see
      // DEFAULT_STATE) rather than defaulting to unlocked.
      setState({ ...DEFAULT_STATE, loading: false, error: err });
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  const hasFeature = (feature) => !!state.features[feature];

  return { ...state, hasFeature, refetch: load };
}
