"use client"

import { useState, Suspense } from "react"
import { signIn } from "next-auth/react"
import { useRouter, useSearchParams } from "next/navigation"
import Link from "next/link"

function SignInForm() {
  const router = useRouter()
  const searchParams = useSearchParams()
  const callbackUrl = searchParams.get("callbackUrl") || "/"

  const [email, setEmail] = useState("")
  const [password, setPassword] = useState("")
  const [error, setError] = useState("")
  const [isLoading, setIsLoading] = useState(false)

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    setError("")
    setIsLoading(true)

    try {
      const result = await signIn("credentials", {
        email,
        password,
        redirect: false,
      })

      if (result?.error) {
        setError("Invalid email or password")
      } else if (result?.ok) {
        router.push(callbackUrl)
        router.refresh()
      }
    } catch (err) {
      setError("An error occurred. Please try again.")
    } finally {
      setIsLoading(false)
    }
  }

  return (
    <div className="relative min-h-screen w-full overflow-hidden bg-gradient-to-br from-[#f4f2fb] via-[#eceefb] to-[#e7e3f6]">
      {/* Decorative pastel circles */}
      <div className="pointer-events-none absolute -top-12 left-10 h-28 w-28 rounded-full bg-purple-300/50" />
      <div className="pointer-events-none absolute top-44 -left-12 h-40 w-40 rounded-full bg-indigo-200/50" />
      <div className="pointer-events-none absolute top-1/2 left-1/3 h-20 w-20 rounded-full bg-sky-300/60" />
      <div className="pointer-events-none absolute bottom-10 left-12 h-24 w-24 rounded-full bg-pink-300/50" />
      <div className="pointer-events-none absolute bottom-8 left-1/2 h-20 w-20 rounded-full bg-yellow-200/70" />
      <div className="pointer-events-none absolute top-12 right-1/3 h-16 w-16 rounded-full bg-violet-200/50" />
      <div className="pointer-events-none absolute bottom-24 right-16 h-12 w-12 rounded-full bg-indigo-200/50" />

      <div className="relative z-10 mx-auto flex min-h-screen max-w-6xl flex-col items-center justify-center gap-12 px-6 md:flex-row md:justify-between">
        {/* Left: Sify wordmark */}
        <div className="flex flex-1 items-center justify-center">
          {/* eslint-disable-next-line @next/next/no-img-element */}
          <img
            src="/sify-logo.png"
            alt="Sify"
            className="h-auto w-48 select-none md:w-80"
          />
        </div>

        {/* Right: Login card */}
        <div className="w-full max-w-md">
          <div className="rounded-2xl bg-white/90 p-8 shadow-xl backdrop-blur">
            <div className="mb-6 text-center">
              <h1 className="text-2xl font-bold text-gray-800">Welcome to InfinitAizen</h1>
              <p className="mt-1 text-sm text-gray-500">Sign in to continue to your workspace</p>
            </div>

            <form className="space-y-4" onSubmit={handleSubmit}>
              <div>
                <label htmlFor="email" className="sr-only">
                  Email address
                </label>
                <input
                  id="email"
                  name="email"
                  type="email"
                  autoComplete="email"
                  required
                  value={email}
                  onChange={(e) => setEmail(e.target.value)}
                  className="block w-full rounded-lg border border-gray-300 px-3 py-2.5 text-sm text-gray-900 placeholder-gray-400 focus:border-indigo-500 focus:outline-none focus:ring-1 focus:ring-indigo-500"
                  placeholder="Email address"
                  disabled={isLoading}
                />
              </div>
              <div>
                <label htmlFor="password" className="sr-only">
                  Password
                </label>
                <input
                  id="password"
                  name="password"
                  type="password"
                  autoComplete="current-password"
                  required
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  className="block w-full rounded-lg border border-gray-300 px-3 py-2.5 text-sm text-gray-900 placeholder-gray-400 focus:border-indigo-500 focus:outline-none focus:ring-1 focus:ring-indigo-500"
                  placeholder="Password"
                  disabled={isLoading}
                />
              </div>

              {error && (
                <div className="rounded-md bg-red-50 p-3">
                  <p className="text-sm text-red-700">{error}</p>
                </div>
              )}

              <button
                type="submit"
                disabled={isLoading}
                className="flex w-full justify-center rounded-lg bg-indigo-600 px-4 py-2.5 text-sm font-medium text-white transition-colors hover:bg-indigo-700 focus:outline-none focus:ring-2 focus:ring-indigo-500 focus:ring-offset-2 disabled:cursor-not-allowed disabled:opacity-50"
              >
                {isLoading ? "Signing in..." : "Sign in"}
              </button>
            </form>

            <p className="mt-6 text-center text-sm text-gray-500">
              Don&apos;t have an account?{" "}
              <Link href="/sign-up" className="font-medium text-indigo-600 hover:text-indigo-500">
                Create a new account
              </Link>
            </p>

            <p className="mt-6 text-center text-xs leading-relaxed text-gray-400">
              Investigate incidents, automate RCA, and resolve faster &mdash; all in one place
            </p>
          </div>
        </div>
      </div>
    </div>
  )
}

export default function SignInPage() {
  return (
    <Suspense
      fallback={
        <div className="flex min-h-screen items-center justify-center bg-[#eceefb]">
          <div className="text-gray-500">Loading...</div>
        </div>
      }
    >
      <SignInForm />
    </Suspense>
  )
}
