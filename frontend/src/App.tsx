import { FormEvent, useMemo, useState } from "react";
import {
  createNewSpacetimeIdentity,
  spacetimeActions,
  startSpacetimeAuthOidc,
  switchSpacetimeAccount,
  useSpacetime,
  type UserRole,
} from "./spacetimeClient";

type VisionResult = {
  session_id: string;
  vehicle?: { year: string; make: string; model: string };
  component?: {
    component: string;
    confidence: number;
    visual_context: string;
    uncertainty: string;
  };
  answer?: string;
  source?: string;
  source_grounded?: boolean;
  status?: string;
  timings_ms?: { inference?: number; total?: number };
  error?: string;
};

const API_BASE = (import.meta.env.VITE_CARVIS_API_URL || "/api").replace(
  /\/$/,
  ""
);

function formatTimestamp(ts?: { microsSinceUnixEpoch: bigint }): string {
  if (!ts?.microsSinceUnixEpoch) return "Just now";
  const ms = Number(ts.microsSinceUnixEpoch / 1000n);
  if (!Number.isFinite(ms) || ms <= 0) return "Just now";
  return new Date(ms).toLocaleTimeString([], {
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  });
}

function roleLabel(role?: string): string {
  if (role === "admin") return "Shop Manager (Admin)";
  if (role === "worker") return "Mechanic (Worker)";
  return "Personal User";
}

function App() {
  const st = useSpacetime();

  // Carvis Vision Query state
  const [photo, setPhoto] = useState<File | null>(null);
  const [question, setQuestion] = useState(
    "What is the torque specification for this component?"
  );
  const [year, setYear] = useState("");
  const [make, setMake] = useState("");
  const [model, setModel] = useState("");
  const [result, setResult] = useState<VisionResult | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [sessionId] = useState(() => crypto.randomUUID());

  // SpacetimeAuth & Role Registration state
  const [editingProfile, setEditingProfile] = useState(false);
  const [nameInput, setNameInput] = useState("");
  const [emailInput, setEmailInput] = useState("");
  const [selectedRole, setSelectedRole] = useState<UserRole>("admin");
  const [shopNameInput, setShopNameInput] = useState("");
  const [joinCodeInput, setJoinCodeInput] = useState("");
  const [authBusy, setAuthBusy] = useState(false);
  const [authMessage, setAuthMessage] = useState("");
  const [authError, setAuthError] = useState("");
  const [showTokenInput, setShowTokenInput] = useState(false);
  const [customToken, setCustomToken] = useState("");
  const [copiedText, setCopiedText] = useState("");

  // Admin Invite state
  const [inviteTarget, setInviteTarget] = useState("");
  const [inviteBusy, setInviteBusy] = useState(false);
  const [inviteFeedback, setInviteFeedback] = useState("");

  // Call filter state for Shop Manager / Mechanic
  const [callFilter, setCallFilter] = useState<"all" | "workers" | "mine">(
    "all"
  );

  const previewUrl = useMemo(
    () => (photo ? URL.createObjectURL(photo) : ""),
    [photo]
  );

  const myPendingInvites = useMemo(() => {
    if (!st.identityHex) return [];
    const myEmail = st.profile?.email?.toLowerCase() || "";
    return st.invites.filter(
      (inv) =>
        inv.status === "pending" &&
        (inv.invitedIdentityHex === st.identityHex ||
          (myEmail && inv.invitedEmail === myEmail))
    );
  }, [st.invites, st.identityHex, st.profile]);

  const filteredCalls = useMemo(() => {
    return st.calls.filter((call) => {
      if (callFilter === "workers") {
        return call.callerRole === "worker";
      }
      if (callFilter === "mine") {
        return (
          call.callerIdentity.toHexString().toLowerCase() === st.identityHex
        );
      }
      return true;
    });
  }, [st.calls, callFilter, st.identityHex]);

  function copyToClipboard(text: string, label: string) {
    navigator.clipboard.writeText(text);
    setCopiedText(label);
    setTimeout(() => setCopiedText(""), 2000);
  }

  function openProfileEditor() {
    setNameInput(st.profile?.name || "");
    setEmailInput(st.profile?.email || "");
    setSelectedRole((st.profile?.role as UserRole) || "admin");
    setShopNameInput(st.shop?.name || "");
    setAuthError("");
    setAuthMessage("");
    setEditingProfile(true);
  }

  async function handleProfileSubmit(event: FormEvent) {
    event.preventDefault();
    setAuthError("");
    setAuthMessage("");
    setAuthBusy(true);
    try {
      if (selectedRole === "worker" && joinCodeInput.trim()) {
        // First register name/email if needed, then join by shop code
        await spacetimeActions.registerOrUpdateProfile({
          name: nameInput.trim() || "Mechanic",
          email: emailInput.trim(),
          requestedRole: "personal",
          shopName: "",
        });
        await spacetimeActions.joinShopByCode(joinCodeInput.trim());
      } else {
        await spacetimeActions.registerOrUpdateProfile({
          name: nameInput.trim(),
          email: emailInput.trim(),
          requestedRole: selectedRole,
          shopName: shopNameInput.trim(),
        });
      }
      setEditingProfile(false);
      setJoinCodeInput("");
      setAuthMessage("Profile and permissions updated in SpacetimeDB.");
    } catch (caught) {
      setAuthError(
        caught instanceof Error
          ? caught.message
          : "Failed to update SpacetimeDB profile."
      );
    } finally {
      setAuthBusy(false);
    }
  }

  async function handleJoinByCode(event: FormEvent) {
    event.preventDefault();
    if (!joinCodeInput.trim()) return;
    setAuthError("");
    setAuthMessage("");
    setAuthBusy(true);
    try {
      await spacetimeActions.joinShopByCode(joinCodeInput.trim());
      setJoinCodeInput("");
      setAuthMessage("Joined shop as Mechanic (Worker)!");
    } catch (caught) {
      setAuthError(
        caught instanceof Error ? caught.message : "Could not join shop."
      );
    } finally {
      setAuthBusy(false);
    }
  }

  async function handleInviteWorker(event: FormEvent) {
    event.preventDefault();
    if (!inviteTarget.trim()) return;
    setInviteFeedback("");
    setInviteBusy(true);
    try {
      await spacetimeActions.inviteWorker(inviteTarget.trim());
      setInviteTarget("");
      setInviteFeedback("Invitation sent via SpacetimeDB.");
    } catch (caught) {
      setInviteFeedback(
        caught instanceof Error ? caught.message : "Failed to send invite."
      );
    } finally {
      setInviteBusy(false);
    }
  }

  async function submitVisionQuery(event: FormEvent) {
    event.preventDefault();
    setError("");
    setResult(null);
    if (!photo) {
      setError("Capture or select a JPEG first.");
      return;
    }

    const queryId = crypto.randomUUID();
    const isShopMember =
      st.connected &&
      st.profile &&
      (st.profile.role === "worker" || st.profile.role === "admin") &&
      Boolean(st.profile.shopId);

    setBusy(true);
    const startedMs = performance.now();

    if (isShopMember) {
      spacetimeActions
        .startShopQuery({
          queryId,
          sessionId,
          vehicleYear: year.trim(),
          vehicleMake: make.trim(),
          vehicleModel: model.trim(),
          question: question.trim(),
        })
        .catch((err) => {
          console.warn("SpacetimeDB startShopQuery warning:", err);
        });
    }

    const body = new FormData();
    body.append("file", photo);
    body.append("question", question);
    body.append("year", year);
    body.append("make", make);
    body.append("model", model);
    body.append("session_id", sessionId);

    try {
      const response = await fetch(`${API_BASE}/vision-query`, {
        method: "POST",
        body,
      });
      const payload = (await response.json()) as VisionResult;
      const elapsedMs = Math.max(
        1,
        Math.round(payload.timings_ms?.total || performance.now() - startedMs)
      );

      if (!response.ok) {
        if (isShopMember) {
          spacetimeActions
            .recordShopQueryResult({
              queryId,
              component: payload.component?.component || "unidentified",
              confidence: payload.component?.confidence || 0,
              status: response.status === 404 ? "refused" : "failed",
              answer:
                payload.error || `Request failed (${response.status})`,
              sourceRef: payload.source || "none",
              sourceGrounded: false,
              latencyMs: elapsedMs,
            })
            .catch((err) => {
              console.warn("SpacetimeDB recordShopQueryResult warning:", err);
            });
        }
        throw new Error(
          payload.error || `Request failed (${response.status})`
        );
      }

      setResult(payload);

      if (isShopMember) {
        spacetimeActions
          .recordShopQueryResult({
            queryId,
            component: payload.component?.component || "confirmed",
            confidence: payload.component?.confidence || 0,
            status: "answered",
            answer: payload.answer || "",
            sourceRef: payload.source || "verified_manual",
            sourceGrounded: Boolean(payload.source_grounded),
            latencyMs: elapsedMs,
          })
          .catch((err) => {
            console.warn("SpacetimeDB recordShopQueryResult warning:", err);
          });
      }

      if (payload.answer && "speechSynthesis" in window) {
        window.speechSynthesis.cancel();
        window.speechSynthesis.speak(
          new SpeechSynthesisUtterance(payload.answer)
        );
      }
    } catch (caught) {
      setError(
        caught instanceof Error ? caught.message : "Vision query failed."
      );
    } finally {
      setBusy(false);
    }
  }

  return (
    <main className="shell">
      {/* Top SpacetimeAuth Bar */}
      <section className="auth-bar card">
        <div className="auth-status">
          <span
            className={`status-dot ${
              st.connected ? "online" : st.connecting ? "connecting" : "offline"
            }`}
          />
          <div>
            <div className="auth-title">
              <strong>SpacetimeAuth</strong>
              {st.profile && (
                <span className={`role-badge role-${st.profile.role}`}>
                  {roleLabel(st.profile.role)}
                </span>
              )}
              {st.shop && (
                <span className="shop-pill">Shop: {st.shop.name}</span>
              )}
            </div>
            <div className="auth-meta">
              {st.connected ? (
                <>
                  <span>
                    Identity:{" "}
                    <code>
                      {st.identityHex.slice(0, 10)}…{st.identityHex.slice(-6)}
                    </code>
                  </span>
                  <button
                    type="button"
                    className="btn-inline"
                    onClick={() => copyToClipboard(st.identityHex, "id")}
                  >
                    {copiedText === "id" ? "Copied ID!" : "Copy Full ID"}
                  </button>
                  {st.profile?.email && <span>· {st.profile.email}</span>}
                </>
              ) : st.connecting ? (
                <span>Connecting to SpacetimeDB Maincloud…</span>
              ) : (
                <span className="error">
                  {st.error || "Disconnected from SpacetimeDB"}
                </span>
              )}
            </div>
          </div>
        </div>

        <div className="auth-actions">
          {st.savedAccounts.length > 1 && (
            <select
              className="account-switcher"
              value={st.token}
              onChange={(e) => switchSpacetimeAccount(e.target.value)}
              aria-label="Switch saved SpacetimeAuth identity"
            >
              {st.savedAccounts.map((acc) => (
                <option key={acc.identityHex} value={acc.token}>
                  {acc.label} ({acc.role || "unregistered"} ·{" "}
                  {acc.identityHex.slice(0, 6)})
                </option>
              ))}
            </select>
          )}
          {st.profile && (
            <button
              type="button"
              className="btn-secondary"
              onClick={openProfileEditor}
            >
              Switch Role / Edit Profile
            </button>
          )}
          <button
            type="button"
            className="btn-secondary"
            onClick={() => createNewSpacetimeIdentity()}
            title="Create a fresh SpacetimeDB identity to test inviting another user"
          >
            + New Identity
          </button>
          <button
            type="button"
            className="btn-secondary"
            onClick={() => setShowTokenInput((v) => !v)}
          >
            Token / OIDC
          </button>
        </div>
      </section>

      {showTokenInput && (
        <section className="card token-drawer">
          <div className="token-row">
            <input
              placeholder="Paste SpacetimeAuth JWT token…"
              value={customToken}
              onChange={(e) => setCustomToken(e.target.value)}
            />
            <button
              type="button"
              onClick={() => {
                if (customToken.trim()) {
                  switchSpacetimeAccount(customToken.trim());
                  setCustomToken("");
                  setShowTokenInput(false);
                }
              }}
            >
              Authenticate with Token
            </button>
            <button
              type="button"
              className="btn-secondary"
              onClick={() => startSpacetimeAuthOidc()}
            >
              SpacetimeAuth OIDC Login
            </button>
          </div>
        </section>
      )}

      {/* Pending Invites Notification Banner */}
      {myPendingInvites.length > 0 && (
        <section className="card invite-banner">
          <div>
            <strong>Shop Invitation Received</strong>
            <p className="hint">
              You have been invited to join a shop as a Mechanic (Worker).
              Accepting grants access to the shop&apos;s Carvis call tables.
            </p>
          </div>
          <div className="invite-banner-list">
            {myPendingInvites.map((inv) => (
              <div key={String(inv.inviteId)} className="invite-banner-item">
                <span>
                  <strong>{inv.shopName}</strong> (invited by{" "}
                  {inv.invitedByName})
                </span>
                <div className="invite-banner-buttons">
                  <button
                    type="button"
                    onClick={() => spacetimeActions.acceptInvite(inv.inviteId)}
                  >
                    Accept & Join Shop
                  </button>
                  <button
                    type="button"
                    className="btn-secondary"
                    onClick={() => spacetimeActions.declineInvite(inv.inviteId)}
                  >
                    Decline
                  </button>
                </div>
              </div>
            ))}
          </div>
        </section>
      )}

      {/* SpacetimeAuth Onboarding / Role Configuration Card */}
      {st.connected && (!st.profile || editingProfile) && (
        <section className="card onboarding-card">
          <div className="section-heading">
            <span>AUTH</span>
            <h2>
              {st.profile
                ? "Update SpacetimeAuth Role & Shop Permissions"
                : "Complete SpacetimeAuth Registration"}
            </h2>
          </div>
          <p className="hint">
            Table permissions in SpacetimeDB are enforced by your account role:
            Shop Managers (<code>admin</code>) see all worker calls and invite
            mechanics, Mechanics (<code>worker</code>) access their shop&apos;s
            calls to Carvis, and Personal users (<code>personal</code>) have no
            access to shop call tables.
          </p>

          <form onSubmit={handleProfileSubmit} className="onboarding-form">
            <div className="form-grid-2">
              <label>
                Display Name
                <input
                  required
                  value={nameInput}
                  onChange={(e) => setNameInput(e.target.value)}
                  placeholder="e.g. Alex Rivera"
                />
              </label>
              <label>
                Email (for shop invites)
                <input
                  type="email"
                  value={emailInput}
                  onChange={(e) => setEmailInput(e.target.value)}
                  placeholder="e.g. alex@shop.com"
                />
              </label>
            </div>

            <div className="role-cards">
              <label
                className={`role-option ${
                  selectedRole === "admin" ? "active" : ""
                }`}
              >
                <input
                  type="radio"
                  name="role"
                  value="admin"
                  checked={selectedRole === "admin"}
                  onChange={() => setSelectedRole("admin")}
                />
                <strong>Shop Manager (Admin)</strong>
                <span>
                  Create/manage a shop, invite workers, and view all calls made
                  by mechanics in your shop.
                </span>
              </label>

              <label
                className={`role-option ${
                  selectedRole === "worker" ? "active" : ""
                }`}
              >
                <input
                  type="radio"
                  name="role"
                  value="worker"
                  checked={selectedRole === "worker"}
                  onChange={() => setSelectedRole("worker")}
                />
                <strong>Mechanic (Worker)</strong>
                <span>
                  Access tables with your shop&apos;s calls to Carvis and log
                  live repair queries.
                </span>
              </label>

              <label
                className={`role-option ${
                  selectedRole === "personal" ? "active" : ""
                }`}
              >
                <input
                  type="radio"
                  name="role"
                  value="personal"
                  checked={selectedRole === "personal"}
                  onChange={() => setSelectedRole("personal")}
                />
                <strong>Personal User (DIY)</strong>
                <span>
                  Use Carvis for personal lookups. No access to shop call tables
                  or team logs.
                </span>
              </label>
            </div>

            {selectedRole === "admin" && (
              <label>
                Shop Name
                <input
                  required
                  value={shopNameInput}
                  onChange={(e) => setShopNameInput(e.target.value)}
                  placeholder="e.g. Apex Performance Garage"
                />
              </label>
            )}

            {selectedRole === "worker" && !st.profile?.shopId && (
              <label>
                Shop Invite Code (or leave blank if you already have a pending
                invite)
                <input
                  value={joinCodeInput}
                  onChange={(e) => setJoinCodeInput(e.target.value)}
                  placeholder="e.g. CARVIS-XXXX-XXXXXX"
                />
              </label>
            )}

            <div className="onboarding-actions">
              <button type="submit" disabled={authBusy}>
                {authBusy ? "Saving to SpacetimeDB…" : "Save Role & Continue"}
              </button>
              {editingProfile && (
                <button
                  type="button"
                  className="btn-secondary"
                  onClick={() => setEditingProfile(false)}
                >
                  Cancel
                </button>
              )}
            </div>
            {authError && <p className="error">{authError}</p>}
          </form>
        </section>
      )}

      {authMessage && <p className="auth-toast">{authMessage}</p>}

      <header>
        <p className="eyebrow">CARVIS / VISION QUERY</p>
        <h1>Look at the part. Ask the manual.</h1>
        <p className="lede">
          A small vertical slice for the glasses workflow: JPEG context in,
          manual-backed answer out.
        </p>
      </header>

      <form className="workspace" onSubmit={submitVisionQuery}>
        <section className="card capture-card">
          <div className="section-heading">
            <span>01</span>
            <h2>Capture context</h2>
          </div>
          <label className="dropzone">
            {previewUrl ? (
              <img src={previewUrl} alt="Selected vehicle component" />
            ) : (
              <span>Choose a JPEG from the iPhone or computer</span>
            )}
            <input
              type="file"
              accept="image/jpeg"
              capture="environment"
              onChange={(event) => setPhoto(event.target.files?.[0] || null)}
            />
          </label>
          <label>
            Question
            <textarea
              value={question}
              onChange={(event) => setQuestion(event.target.value)}
              rows={3}
            />
          </label>
        </section>

        <section className="card">
          <div className="section-heading">
            <span>02</span>
            <h2>Confirm vehicle</h2>
          </div>
          <p className="hint">
            Visual identification never replaces these manual-selection fields.
          </p>
          <div className="vehicle-grid">
            <label>
              Year
              <input
                value={year}
                onChange={(event) => setYear(event.target.value)}
                placeholder="e.g. 2022"
              />
            </label>
            <label>
              Make
              <input
                value={make}
                onChange={(event) => setMake(event.target.value)}
                placeholder="e.g. subaru"
              />
            </label>
            <label>
              Model
              <input
                value={model}
                onChange={(event) => setModel(event.target.value)}
                placeholder="e.g. wrx"
              />
            </label>
          </div>
          <button disabled={busy}>
            {busy ? "Reading manual…" : "Ask Carvis"}
          </button>
          {error && <p className="error">{error}</p>}
        </section>
      </form>

      <section className="card result-card" aria-live="polite">
        <div className="section-heading">
          <span>03</span>
          <h2>Answer</h2>
        </div>
        {!result && !busy && (
          <p className="empty">Your source-grounded result will appear here.</p>
        )}
        {busy && (
          <p className="empty">
            Identifying the component, then searching the matching manual…
          </p>
        )}
        {result?.component && (
          <div className="component">
            <strong>{result.component.component}</strong>
            <span>
              {Math.round(result.component.confidence * 100)}% visual confidence
            </span>
            <p>{result.component.visual_context}</p>
          </div>
        )}
        {result?.answer && <blockquote>{result.answer}</blockquote>}
        {result?.source && <p className="source">Source: {result.source}</p>}
      </section>

      {/* Section 04: Role-Gated SpacetimeDB Shop Console */}
      {st.connected && st.profile && (
        <section className="card shop-console">
          <div className="section-heading">
            <span>04</span>
            <h2>
              {st.profile.role === "admin"
                ? "Shop Manager Console (Admin Access)"
                : st.profile.role === "worker"
                  ? "Shop Mechanic Console (Shop Call Access)"
                  : "Personal Garage Mode (Shop Tables Restricted)"}
            </h2>
          </div>

          {/* PERSONAL USER VIEW: Strictly blocked from shop call tables */}
          {st.profile.role === "personal" && (
            <div className="personal-restricted">
              <div className="permission-notice">
                <strong>Shop Call Tables Locked</strong>
                <p className="hint">
                  Your account is set to <code>personal</code>. Per SpacetimeDB
                  table permissions, personal users do not have access to{" "}
                  <code>shop_calls</code> or <code>shop_call_results</code>. To
                  access shop call tables, ask a Shop Manager to invite your
                  SpacetimeDB Identity or enter a Shop Invite Code below.
                </p>
              </div>

              <form onSubmit={handleJoinByCode} className="inline-form">
                <input
                  value={joinCodeInput}
                  onChange={(e) => setJoinCodeInput(e.target.value)}
                  placeholder="Enter Shop Invite Code (e.g. CARVIS-XXXX-XXXXXX)"
                />
                <button type="submit" disabled={authBusy}>
                  Join Shop as Mechanic
                </button>
              </form>
              {authError && <p className="error">{authError}</p>}
            </div>
          )}

          {/* SHOP MANAGER (ADMIN) & MECHANIC (WORKER) VIEWS */}
          {(st.profile.role === "admin" || st.profile.role === "worker") && (
            <div className="shop-workspace">
              {/* Admin-Only Invite & Team Management Panel */}
              {st.profile.role === "admin" && (
                <div className="admin-panel">
                  <div className="admin-box">
                    <h3>Invite User to Work in Shop</h3>
                    <p className="hint">
                      Invite a user by their SpacetimeDB Identity (hex) or
                      registered email address, or share the shop invite code.
                    </p>
                    <form onSubmit={handleInviteWorker} className="inline-form">
                      <input
                        value={inviteTarget}
                        onChange={(e) => setInviteTarget(e.target.value)}
                        placeholder="Paste user SpacetimeDB Identity hex or email…"
                      />
                      <button type="submit" disabled={inviteBusy}>
                        {inviteBusy ? "Sending…" : "Send Invite"}
                      </button>
                    </form>
                    {inviteFeedback && (
                      <p className="source">{inviteFeedback}</p>
                    )}

                    {st.shop?.inviteCode && (
                      <div className="invite-code-bar">
                        <span>
                          Shop Invite Code:{" "}
                          <strong>{st.shop.inviteCode}</strong>
                        </span>
                        <button
                          type="button"
                          className="btn-inline"
                          onClick={() =>
                            copyToClipboard(st.shop!.inviteCode, "code")
                          }
                        >
                          {copiedText === "code" ? "Copied!" : "Copy Code"}
                        </button>
                      </div>
                    )}

                    {st.invites.length > 0 && (
                      <div className="sub-list">
                        <h4>Sent Shop Invitations</h4>
                        {st.invites.map((inv) => (
                          <div
                            key={String(inv.inviteId)}
                            className="sub-list-row"
                          >
                            <span>
                              <code>
                                {inv.invitedEmail ||
                                  `${inv.invitedIdentityHex.slice(0, 12)}…`}
                              </code>{" "}
                              —{" "}
                              <span className={`status-pill ${inv.status}`}>
                                {inv.status}
                              </span>
                            </span>
                            {inv.status === "pending" && (
                              <button
                                type="button"
                                className="btn-inline danger"
                                onClick={() =>
                                  spacetimeActions.revokeInvite(inv.inviteId)
                                }
                              >
                                Revoke
                              </button>
                            )}
                          </div>
                        ))}
                      </div>
                    )}
                  </div>

                  <div className="admin-box">
                    <h3>Shop Team Roster ({st.members.length})</h3>
                    <div className="sub-list">
                      {st.members.map((member) => (
                        <div key={member.identityHex} className="sub-list-row">
                          <div>
                            <strong>{member.name}</strong>{" "}
                            <span
                              className={`role-badge role-${member.role}`}
                            >
                              {member.role}
                            </span>
                            <div className="tiny-meta">
                              {member.email ? `${member.email} · ` : ""}
                              <code>{member.identityHex.slice(0, 12)}…</code>
                            </div>
                          </div>
                          {member.role === "worker" && (
                            <button
                              type="button"
                              className="btn-inline danger"
                              onClick={() =>
                                spacetimeActions.removeShopWorker(
                                  member.identityHex
                                )
                              }
                            >
                              Remove
                            </button>
                          )}
                        </div>
                      ))}
                    </div>
                  </div>
                </div>
              )}

              {/* Mechanic Shop Info Bar */}
              {st.profile.role === "worker" && st.shop && (
                <div className="worker-shop-bar">
                  <span>
                    Connected to <strong>{st.shop.name}</strong> · Manager:{" "}
                    {st.shop.ownerName} · Team Members: {st.members.length}
                  </span>
                </div>
              )}

              {/* Live Shop Calls Table */}
              <div className="calls-section">
                <div className="calls-header">
                  <div>
                    <h3>
                      {st.profile.role === "admin"
                        ? "All Shop & Worker Calls to Carvis"
                        : "Shop Calls to Carvis"}
                    </h3>
                    <p className="hint">
                      {st.profile.role === "admin"
                        ? "As Shop Manager (admin), you have live visibility into all calls made by workers in your shop."
                        : "As a Shop Mechanic (worker), you have live access to your shop's Carvis call tables."}
                    </p>
                  </div>
                  <div className="filter-tabs">
                    <button
                      type="button"
                      className={`btn-tab ${
                        callFilter === "all" ? "active" : ""
                      }`}
                      onClick={() => setCallFilter("all")}
                    >
                      All Shop Calls ({st.calls.length})
                    </button>
                    {st.profile.role === "admin" && (
                      <button
                        type="button"
                        className={`btn-tab ${
                          callFilter === "workers" ? "active" : ""
                        }`}
                        onClick={() => setCallFilter("workers")}
                      >
                        Worker Calls Only (
                        {
                          st.calls.filter((c) => c.callerRole === "worker")
                            .length
                        }
                        )
                      </button>
                    )}
                    <button
                      type="button"
                      className={`btn-tab ${
                        callFilter === "mine" ? "active" : ""
                      }`}
                      onClick={() => setCallFilter("mine")}
                    >
                      My Calls
                    </button>
                  </div>
                </div>

                {filteredCalls.length === 0 ? (
                  <p className="empty">
                    No Carvis calls recorded for this view yet. Run a Vision
                    Query above to stream it live to your shop!
                  </p>
                ) : (
                  <div className="calls-list">
                    {filteredCalls.map((call) => {
                      const res = st.results[call.id];
                      return (
                        <article key={call.id} className="call-card">
                          <div className="call-card-top">
                            <div className="call-user">
                              <strong>{call.callerName}</strong>
                              <span
                                className={`role-badge role-${call.callerRole}`}
                              >
                                {call.callerRole}
                              </span>
                              <span className="vehicle-tag">
                                {[
                                  call.vehicleYear,
                                  call.vehicleMake,
                                  call.vehicleModel,
                                ]
                                  .filter(Boolean)
                                  .join(" ") || "Unspecified vehicle"}
                              </span>
                            </div>
                            <div className="call-meta">
                              <span className={`status-pill ${call.status}`}>
                                {call.status}
                              </span>
                              <span>{formatTimestamp(call.createdAt)}</span>
                              {res?.latencyMs ? (
                                <span>{res.latencyMs} ms</span>
                              ) : null}
                            </div>
                          </div>

                          <p className="call-question">“{call.question}”</p>

                          {call.component && (
                            <p className="call-component">
                              Component: <strong>{call.component}</strong> (
                              {Math.round(call.confidence * 100)}% confidence)
                            </p>
                          )}

                          {res?.answer && (
                            <div className="call-answer">
                              <p>{res.answer}</p>
                              {res.sourceRef && (
                                <span className="source">
                                  Source: {res.sourceRef}
                                </span>
                              )}
                            </div>
                          )}
                        </article>
                      );
                    })}
                  </div>
                )}
              </div>
            </div>
          )}
        </section>
      )}
    </main>
  );
}

export default App;
