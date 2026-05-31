'use client'
import { useEffect, useState } from 'react'
import { useRouter } from 'next/navigation'
import { getProfile, getAvailableCounties, updateCounties, openBillingPortal } from '@/lib/api'
import { supabase } from '@/lib/supabase'

export default function SettingsPage() {
  const router = useRouter()
  const [profile, setProfile] = useState<any>(null)
  const [allCounties, setAllCounties] = useState<string[]>([])
  const [selected, setSelected] = useState<string[]>([])
  const [saving, setSaving] = useState(false)
  const [saved, setSavedMsg] = useState(false)
  const [search, setSearch] = useState('')

  useEffect(() => {
    async function load() {
      const [prof, counties] = await Promise.all([getProfile(), getAvailableCounties()])
      setProfile(prof)
      setSelected(prof.counties ?? [])
      setAllCounties(counties.counties ?? [])
    }
    load()
  }, [])

  function toggleCounty(county: string) {
    setSelected(prev => {
      if (prev.includes(county)) return prev.filter(c => c !== county)
      const limit = profile?.county_limit
      if (limit && prev.length >= limit) {
        alert(`Your plan allows up to ${limit} counties. Upgrade to add more.`)
        return prev
      }
      return [...prev, county]
    })
  }

  async function saveCounties() {
    setSaving(true)
    try {
      await updateCounties(selected)
      setSavedMsg(true)
      setTimeout(() => setSavedMsg(false), 2000)
    } finally {
      setSaving(false)
    }
  }

  const filtered = allCounties.filter(c => c.toLowerCase().includes(search.toLowerCase()))
  const limit = profile?.county_limit

  return (
    <div className="min-h-screen bg-gray-50">
      <header className="bg-white border-b border-gray-200 px-6 py-4 flex items-center gap-4">
        <button onClick={() => router.push('/dashboard')} className="text-blue-600 hover:underline text-sm">← Dashboard</button>
        <h1 className="text-xl font-bold text-gray-900">Settings</h1>
      </header>

      <main className="max-w-3xl mx-auto px-4 py-8 space-y-8">
        {/* Plan */}
        <section className="bg-white rounded-xl border border-gray-200 p-6">
          <h2 className="text-lg font-semibold mb-1">Plan</h2>
          {profile && (
            <div className="flex items-center justify-between">
              <div>
                <p className="capitalize font-medium text-gray-900">{profile.plan} plan</p>
                <p className="text-sm text-gray-500">
                  {limit ? `Up to ${limit} counties` : 'Unlimited counties'}
                  {profile.plan_ends_at && ` · Renews ${new Date(profile.plan_ends_at).toLocaleDateString()}`}
                </p>
              </div>
              <div className="flex gap-2">
                {profile.plan === 'free' && (
                  <button onClick={() => router.push('/pricing')}
                    className="bg-blue-600 text-white px-4 py-2 rounded-lg text-sm font-medium hover:bg-blue-700">
                    Upgrade
                  </button>
                )}
                {profile.plan !== 'free' && (
                  <button onClick={openBillingPortal}
                    className="border border-gray-300 px-4 py-2 rounded-lg text-sm font-medium hover:bg-gray-50">
                    Manage billing
                  </button>
                )}
              </div>
            </div>
          )}
        </section>

        {/* County selector */}
        <section className="bg-white rounded-xl border border-gray-200 p-6">
          <div className="flex items-center justify-between mb-4">
            <div>
              <h2 className="text-lg font-semibold">Your counties</h2>
              <p className="text-sm text-gray-500">
                {selected.length} selected{limit ? ` / ${limit} max` : ''}
              </p>
            </div>
            <button onClick={saveCounties} disabled={saving}
              className="bg-blue-600 text-white px-4 py-2 rounded-lg text-sm font-medium hover:bg-blue-700 disabled:opacity-50">
              {saving ? 'Saving...' : saved ? 'Saved ✓' : 'Save'}
            </button>
          </div>

          {/* Selected pills */}
          {selected.length > 0 && (
            <div className="flex flex-wrap gap-2 mb-4">
              {selected.map(c => (
                <span key={c} className="flex items-center gap-1 bg-blue-100 text-blue-700 text-sm px-3 py-1 rounded-full">
                  {c}
                  <button onClick={() => toggleCounty(c)} className="hover:text-blue-900 ml-1">×</button>
                </span>
              ))}
            </div>
          )}

          <input
            type="text"
            placeholder="Search counties..."
            value={search}
            onChange={e => setSearch(e.target.value)}
            className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm mb-3 focus:outline-none focus:ring-2 focus:ring-blue-500"
          />

          <div className="grid grid-cols-2 sm:grid-cols-3 gap-1 max-h-72 overflow-y-auto">
            {filtered.map(county => (
              <button
                key={county}
                onClick={() => toggleCounty(county)}
                className={`text-left text-sm px-3 py-2 rounded-lg transition-colors ${
                  selected.includes(county)
                    ? 'bg-blue-600 text-white'
                    : 'hover:bg-gray-100 text-gray-700'
                }`}
              >
                {county}
              </button>
            ))}
          </div>
        </section>

        {/* Account */}
        <section className="bg-white rounded-xl border border-gray-200 p-6">
          <h2 className="text-lg font-semibold mb-4">Account</h2>
          {profile && <p className="text-sm text-gray-500 mb-4">{profile.email}</p>}
          <button
            onClick={async () => { await supabase.auth.signOut(); router.push('/login') }}
            className="text-sm text-red-500 hover:underline"
          >
            Sign out
          </button>
        </section>
      </main>
    </div>
  )
}
