import { Activity, LockKeyhole } from "lucide-react";
import { useState } from "react";
import { useLogin } from "../api";
import { Button } from "../components/ui";

export default function Login() {
  const login = useLogin();
  const [password, setPassword] = useState("");
  return (
    <div className="grid min-h-screen place-items-center px-4">
      <form
        className="w-full max-w-sm rounded-2xl border border-line bg-panel p-6"
        onSubmit={(e) => { e.preventDefault(); if (password) login.mutate(password); }}
      >
        <div className="flex items-center gap-2.5">
          <div className="grid size-9 place-items-center rounded-lg bg-accent"><Activity className="size-5 text-white" strokeWidth={2.5} /></div>
          <div>
            <div className="font-semibold leading-tight">Trading Universe</div>
            <div className="text-xs text-ink-3">Enter your password to continue</div>
          </div>
        </div>
        <label className="mt-6 block text-xs font-medium text-ink-3" htmlFor="pw">Password</label>
        <div className="mt-1.5 flex items-center gap-2 rounded-xl border border-line bg-panel-2 px-3 focus-within:border-accent/60">
          <LockKeyhole className="size-4 text-ink-3" />
          <input id="pw" type="password" autoFocus autoComplete="current-password" value={password}
            onChange={(e) => setPassword(e.target.value)} className="w-full bg-transparent py-2 text-sm outline-none" />
        </div>
        {login.error && <div className="mt-3 text-sm text-down">{login.error.message}</div>}
        <Button type="submit" loading={login.isPending} className="mt-5 w-full justify-center">Log in</Button>
      </form>
    </div>
  );
}
