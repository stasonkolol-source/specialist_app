import golden from '@sosed/links/golden.json' with { type: 'json' };
import { describe, expect, it } from 'vitest';

import { startTarget } from './startapp.ts';

describe('startTarget', () => {
  it('is null without a deep link', () => {
    expect(startTarget(null)).toBeNull();
    expect(startTarget('')).toBeNull();
  });

  it('opens home for `h` and for targets whose screens come in later steps', () => {
    expect(startTarget('h')).toBe('/');
    expect(startTarget('h_rAB12CD')).toBe('/');
    // у остальных целей (коды «Вещей», `h`) экрана нет — на главную
    const ready = new Set([
      'legal',
      'specialist',
      'job',
      'new_job',
      'mine',
      'chat',
      'deal',
      'dispute',
      'review_invite',
      'review',
    ]);
    for (const { param, link } of golden.valid) {
      if (!ready.has(link.type)) expect(startTarget(param)).toBe('/');
    }
  });

  it('opens the job S15 for `j_` links, with or without attribution (5.3)', () => {
    const jobs = golden.valid.filter(({ link }) => link.type === 'job');
    expect(jobs.length).toBeGreaterThan(0);
    for (const { param, link } of jobs) {
      expect(startTarget(param)).toBe(`/jobs/${'id' in link ? link.id : ''}`);
    }
  });

  it('opens the specialist card S08 for `s_` links, with or without attribution (4.5)', () => {
    const specialists = golden.valid.filter(({ link }) => link.type === 'specialist');
    expect(specialists.length).toBeGreaterThan(0);
    for (const { param, link } of specialists) {
      expect(startTarget(param)).toBe(`/specialists/${'id' in link ? link.id : ''}`);
    }
  });

  it('opens the S48 tab for links to the rules and the privacy policy (bot /terms, /privacy)', () => {
    expect(startTarget('l_terms')).toBe('/legal/terms');
    expect(startTarget('l_privacy')).toBe('/legal/privacy');
    expect(startTarget('l_privacy_rAB12CD')).toBe('/legal/privacy');
  });

  it('opens the job wizard S20a for `n` and my jobs S22 for `m_jobs` (bot /new, /jobs; 5.6)', () => {
    expect(startTarget('n')).toBe('/jobs/new');
    expect(startTarget('n_rAB12CD')).toBe('/jobs/new');
    expect(startTarget('m_jobs')).toBe('/jobs/mine');
    expect(startTarget('m_jobs_rAB12CD')).toBe('/jobs/mine');
  });

  it('opens alerts S18, the feed by alerts, S38 and the cabinet — bot /alerts, /feed, B1 (5.7)', () => {
    expect(startTarget('m_alerts')).toBe('/jobs/alerts');
    expect(startTarget('m_feed_rAB12CD')).toBe('/jobs?alerts=true');
    expect(startTarget('m_availability')).toBe('/cabinet/availability');
    expect(startTarget('m_profile')).toBe('/cabinet');
  });

  it('opens settings S43 and account deletion S45 — buttons of the bot /settings (4.9)', () => {
    expect(startTarget('m_settings')).toBe('/settings');
    expect(startTarget('m_deletion')).toBe('/profile/delete');
    expect(startTarget('m_reviews')).toBe('/deals?tab=reviews');
  });

  it('opens my responses S17 and the portfolio S37 — outcomes of a response, portfolio refusal', () => {
    expect(startTarget('m_responses')).toBe('/jobs/responses');
    expect(startTarget('m_portfolio')).toBe('/cabinet/portfolio');
  });

  it('opens the review form S27 for `rv_` links — «Открыть форму отзыва» of a review request', () => {
    const reviews = golden.valid.filter(({ link }) => link.type === 'review');
    expect(reviews.length).toBeGreaterThan(0);
    for (const { param, link } of reviews) {
      expect(startTarget(param)).toBe(`/deals/${'id' in link ? link.id : ''}/review`);
    }
  });

  it('opens the dialog S30 for `c_` links — «Ответить» of a message notice (6.4)', () => {
    const chats = golden.valid.filter(({ link }) => link.type === 'chat');
    expect(chats.length).toBeGreaterThan(0);
    for (const { param, link } of chats) {
      expect(startTarget(param)).toBe(`/messages/${'id' in link ? link.id : ''}`);
    }
  });

  it('opens the deal S26 for `d_` links — buttons of deal notifications (6.2)', () => {
    const deals = golden.valid.filter(({ link }) => link.type === 'deal');
    expect(deals.length).toBeGreaterThan(0);
    for (const { param, link } of deals) {
      expect(startTarget(param)).toBe(`/deals/${'id' in link ? link.id : ''}`);
    }
  });

  it('opens the dispute S52 for `p_` links — «Есть проблема» and dispute notices (6.1c)', () => {
    const disputes = golden.valid.filter(({ link }) => link.type === 'dispute');
    expect(disputes.length).toBeGreaterThan(0);
    for (const { param, link } of disputes) {
      expect(startTarget(param)).toBe(`/deals/${'id' in link ? link.id : ''}/dispute`);
    }
  });

  it("opens the invite review S56 for `ri_` links — the specialist's invite (7.6а)", () => {
    const invites = golden.valid.filter(({ link }) => link.type === 'review_invite');
    expect(invites.length).toBeGreaterThan(0);
    for (const { param, link } of invites) {
      expect(startTarget(param)).toBe(`/review-invites/${'id' in link ? link.id : ''}`);
    }
  });

  it('opens home for broken and foreign codes', () => {
    for (const param of golden.invalid.filter(Boolean)) expect(startTarget(param)).toBe('/');
  });
});
