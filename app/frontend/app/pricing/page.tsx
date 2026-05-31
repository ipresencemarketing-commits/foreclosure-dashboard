'use client'
import { createCheckout } from '@/lib/api'

const plans = [
  {
    name: 'Starter',
    price: 99,
    key: 'starter' as const,
    counties: 5,
    features: ['Up to 5 counties', 'All listings daily', 'Sale date + time', 'Owner info (GIS)', 'Investment scoring', 'Save listings'],
  },
  {
    name: 'Pro',
    price: 199,
    key: 'pro' as const,
    counties: null,
    features: ['Unlimited counties', 'All listings daily', 'Sale date + time', 'Owner info (GIS)', 'Investment scoring', 'Save listings', 'Priority email alerts', 'All of Virginia'],
    highlighted: true,
  },
]

export default function PricingPage() {
  return (
    <div className="min-h-screen bg-gray-50 py-16 px-4">
      <div className="max-w-4xl mx-auto">
        <div className="text-center mb-12">
          <h1 className="text-4xl font-bold text-gray-900">Find deals before anyone else</h1>
          <p className="text-xl text-gray-500 mt-3">Daily Virginia foreclosure leads delivered straight to you</p>
        </div>

        <div className="grid md:grid-cols-2 gap-8">
          {plans.map(plan => (
            <div
              key={plan.key}
              className={`bg-white rounded-2xl shadow-sm p-8 border-2 ${plan.highlighted ? 'border-blue-500' : 'border-gray-100'}`}
            >
              {plan.highlighted && (
                <span className="inline-block bg-blue-500 text-white text-xs font-semibold px-3 py-1 rounded-full mb-4">Most Popular</span>
              )}
              <h2 className="text-2xl font-bold text-gray-900">{plan.name}</h2>
              <div className="mt-2 mb-6">
                <span className="text-4xl font-bold">${plan.price}</span>
                <span className="text-gray-400">/month</span>
              </div>
              <p className="text-gray-500 mb-6">
                {plan.counties ? `Up to ${plan.counties} counties` : 'All 95 Virginia counties'}
              </p>
              <ul className="space-y-3 mb-8">
                {plan.features.map(f => (
                  <li key={f} className="flex items-center gap-2 text-gray-700">
                    <span className="text-green-500">✓</span> {f}
                  </li>
                ))}
              </ul>
              <button
                onClick={() => createCheckout(plan.key)}
                className={`w-full py-3 rounded-xl font-semibold ${plan.highlighted ? 'bg-blue-600 text-white hover:bg-blue-700' : 'bg-gray-900 text-white hover:bg-gray-800'}`}
              >
                Get started
              </button>
            </div>
          ))}
        </div>

        <p className="text-center text-gray-400 text-sm mt-8">Cancel anytime. No contracts.</p>
      </div>
    </div>
  )
}
