import type { MeOut } from '@sosed/api-client';
import { configureApiClient, getIdentityGetMeQueryKey, setSession } from '@sosed/api-client';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { renderHook } from '@testing-library/react';
import type { ReactNode } from 'react';
import { afterEach, describe, expect, it, vi } from 'vitest';

import { consentGate, nextOnboardingStep, onboardingStep, useConsentGate } from './onboarding.ts';

const DONE = { home_city_id: 1, intent: 'client', consent_required: false } as const;
const NEW = { home_city_id: null, intent: null, consent_required: true } as const;

describe('onboardingStep', () => {
  it('starts a new user with language and city', () => {
    expect(onboardingStep(NEW)).toBe('language');
  });

  it('resumes where the user stopped', () => {
    expect(onboardingStep({ ...NEW, home_city_id: 1 })).toBe('intent');
    expect(onboardingStep({ ...DONE, consent_required: true })).toBe('rules');
  });

  it('sends a returning user with current consents home', () => {
    expect(onboardingStep(DONE)).toBeNull();
  });

  it('shows only the rules again after a new legal version', () => {
    // город и намерение уже есть: S02a и S02b не повторяются
    expect(onboardingStep({ ...DONE, consent_required: true })).toBe('rules');
  });
});

describe('nextOnboardingStep', () => {
  it('always goes from language to intent', () => {
    expect(nextOnboardingStep('language', DONE)).toBe('intent');
  });

  it('asks for the rules only without current consents', () => {
    expect(nextOnboardingStep('intent', { ...DONE, consent_required: true })).toBe('rules');
    expect(nextOnboardingStep('intent', DONE)).toBeNull();
    expect(nextOnboardingStep('rules', DONE)).toBeNull();
  });
});

describe('consent gate', () => {
  afterEach(() => setSession(null));

  it('requires S02c for creating actions until consents are current', () => {
    expect(consentGate(undefined)).toBe('unknown');
    expect(consentGate({ consent_required: true })).toBe('required');
    expect(consentGate({ consent_required: false })).toBe('accepted');
  });

  it('reads /me from the cache filled at sign-in', () => {
    const fetch = vi.fn();
    configureApiClient({ fetch });
    setSession({ accessToken: 'a', refreshToken: 'r' });
    const client = new QueryClient({ defaultOptions: { queries: { staleTime: Infinity } } });
    client.setQueryData(getIdentityGetMeQueryKey(), { consent_required: true } as MeOut);
    const wrapper = ({ children }: { children: ReactNode }) => (
      <QueryClientProvider client={client}>{children}</QueryClientProvider>
    );

    const { result } = renderHook(() => useConsentGate(), { wrapper });

    expect(result.current).toBe('required');
    expect(fetch).not.toHaveBeenCalled();
  });

  it('does not ask the server without a session', () => {
    const fetch = vi.fn();
    configureApiClient({ fetch });
    const client = new QueryClient();
    const wrapper = ({ children }: { children: ReactNode }) => (
      <QueryClientProvider client={client}>{children}</QueryClientProvider>
    );

    const { result } = renderHook(() => useConsentGate(), { wrapper });

    expect(result.current).toBe('unknown');
    expect(fetch).not.toHaveBeenCalled();
  });
});
