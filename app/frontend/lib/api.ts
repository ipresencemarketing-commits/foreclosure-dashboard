import { supabase } from './supabase'

const API = process.env.NEXT_PUBLIC_API_URL

async function authHeaders() {
  const { data } = await supabase.auth.getSession()
  const token = data.session?.access_token
  return { 'Authorization': `Bearer ${token}`, 'Content-Type': 'application/json' }
}

export async function getListings(params: {
  county?: string
  stage?: string
  priority?: string
  days_until_sale_max?: number
  page?: number
} = {}) {
  const qs = new URLSearchParams()
  Object.entries(params).forEach(([k, v]) => v !== undefined && qs.set(k, String(v)))
  const res = await fetch(`${API}/listings/?${qs}`, { headers: await authHeaders() })
  if (!res.ok) throw new Error('Failed to fetch listings')
  return res.json()
}

export async function getListing(id: string) {
  const res = await fetch(`${API}/listings/${id}`, { headers: await authHeaders() })
  if (!res.ok) throw new Error('Listing not found')
  return res.json()
}

export async function saveListing(id: string) {
  await fetch(`${API}/listings/${id}/save`, { method: 'POST', headers: await authHeaders() })
}

export async function unsaveListing(id: string) {
  await fetch(`${API}/listings/${id}/save`, { method: 'DELETE', headers: await authHeaders() })
}

export async function getSavedListings() {
  const res = await fetch(`${API}/listings/saved/all`, { headers: await authHeaders() })
  return res.json()
}

export async function getProfile() {
  const res = await fetch(`${API}/users/me`, { headers: await authHeaders() })
  return res.json()
}

export async function updateCounties(counties: string[]) {
  const res = await fetch(`${API}/users/me/counties`, {
    method: 'PUT',
    headers: await authHeaders(),
    body: JSON.stringify({ counties }),
  })
  return res.json()
}

export async function getAvailableCounties() {
  const res = await fetch(`${API}/users/counties/available`, { headers: await authHeaders() })
  return res.json()
}

export async function createCheckout(plan: 'starter' | 'pro') {
  const res = await fetch(`${API}/billing/checkout/${plan}`, {
    method: 'POST',
    headers: await authHeaders(),
  })
  const data = await res.json()
  window.location.href = data.checkout_url
}

export async function openBillingPortal() {
  const res = await fetch(`${API}/billing/portal`, {
    method: 'POST',
    headers: await authHeaders(),
  })
  const data = await res.json()
  window.location.href = data.portal_url
}
