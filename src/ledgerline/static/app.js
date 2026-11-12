let authToken = localStorage.getItem("ledgerline_token") || null;
let currentUser = null;
let accounts = [];
let activeView = "accounts";
let toastTimer;

const money = new Intl.NumberFormat("en-IN", { maximumFractionDigits: 0 });

// DOM Elements
const grid = document.querySelector("#account-grid");
const rows = document.querySelector("#activity-rows");
const search = document.querySelector("#global-search");
const dialog = document.querySelector("#action-dialog");
const dialogContent = document.querySelector("#dialog-content");

// --- API Helpers ---

async function apiRequest(path, options = {}) {
  const headers = { "Content-Type": "application/json", ...(options.headers || {}) };
  if (authToken) {
    headers["Authorization"] = `Bearer ${authToken}`;
  }

  try {
    const res = await fetch(path, { ...options, headers, credentials: "same-origin" });
    const data = await res.json().catch(() => ({}));

    if (res.status === 401) {
      if (authToken) {
        handleLogout(false);
        showToast("Session expired. Please sign in again.");
      }
      throw new Error(data.detail || "Authentication required");
    }

    if (!res.ok) {
      throw new Error(data.detail || `Request failed with status ${res.status}`);
    }

    return data;
  } catch (err) {
    console.warn(`API call to ${path} failed:`, err.message);
    throw err;
  }
}

function escapeHtml(value) {
  return String(value ?? "").replace(/[&<>"']/g, (char) => ({
    "&": "&amp;",
    "<": "&lt;",
    ">": "&gt;",
    '"': "&quot;",
    "'": "&#39;",
  })[char]);
}

function showToast(message) {
  const toast = document.querySelector("#toast");
  if (!toast) return;
  toast.textContent = message;
  toast.classList.add("visible");
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => toast.classList.remove("visible"), 3500);
}

// --- Session & Auth UI Management ---

function updateAuthUI() {
  const roleBadge = document.querySelector("#user-role-badge");
  const roleText = document.querySelector("#role-badge-text");
  const sidebarAvatar = document.querySelector("#sidebar-avatar");
  const sidebarName = document.querySelector("#sidebar-name");
  const sidebarRole = document.querySelector("#sidebar-role");
  const sidebarAction = document.querySelector("#sidebar-auth-arrow");
  const topAvatar = document.querySelector("#top-avatar");
  const topBubble = document.querySelector("#top-avatar-bubble");
  const topLabel = document.querySelector("#top-avatar-label");
  const authPrompt = document.querySelector("#auth-prompt-card");
  const workspaceNote = document.querySelector("#workspace-note");

  if (roleBadge) {
    roleBadge.className = "user-role-badge";
  }

  if (authToken && currentUser) {
    const roleKey = (currentUser.role || "").toLowerCase();
    const roleDisplay = roleKey === "admin"
      ? "Administrator"
      : roleKey === "auditor"
        ? "Auditor"
        : "Account Holder";

    if (roleBadge) {
      roleBadge.classList.add(`role-${roleKey}`);
    }
    if (roleText) roleText.textContent = roleDisplay;

    const initials = currentUser.email.slice(0, 2).toUpperCase();
    if (sidebarAvatar) sidebarAvatar.textContent = initials;
    if (sidebarName) sidebarName.textContent = currentUser.email;
    if (sidebarRole) sidebarRole.textContent = roleDisplay;
    if (sidebarAction) sidebarAction.textContent = "🚪";

    if (topAvatar) topAvatar.classList.add("authenticated");
    if (topBubble) topBubble.textContent = initials;
    if (topLabel) topLabel.textContent = currentUser.email.split("@")[0];

    if (authPrompt) authPrompt.classList.add("hidden");
    if (workspaceNote) {
      document.querySelector("#workspace-title").textContent = "Live Workspace";
      document.querySelector("#workspace-subtitle").textContent = `${roleDisplay} Session`;
      document.querySelector("#workspace-dot").style.background = "#39c883";
    }
  } else {
    if (roleText) roleText.textContent = "Guest";
    if (sidebarAvatar) sidebarAvatar.textContent = "🔑";
    if (sidebarName) sidebarName.textContent = "Sign in";
    if (sidebarRole) sidebarRole.textContent = "Click to authenticate";
    if (sidebarAction) sidebarAction.textContent = "→";

    if (topAvatar) topAvatar.classList.remove("authenticated");
    if (topBubble) topBubble.textContent = "🔑";
    if (topLabel) topLabel.textContent = "Sign in";

    if (authPrompt) authPrompt.classList.remove("hidden");
    if (workspaceNote) {
      document.querySelector("#workspace-title").textContent = "Signed Out";
      document.querySelector("#workspace-subtitle").textContent = "Authentication Required";
      document.querySelector("#workspace-dot").style.background = "#e4a654";
    }
  }

  updateNavigationForRole();
}

function updateNavigationForRole() {
  const role = currentUser ? (currentUser.role || "").toLowerCase() : "guest";

  const navTransfer = document.querySelector("#nav-transfer");
  const navAudit = document.querySelector("#nav-audit");
  const navUsers = document.querySelector("#nav-users");
  const addAccountBtn = document.querySelector("#add-account");

  if (role === "admin") {
    if (navTransfer) navTransfer.classList.remove("hidden");
    if (navAudit) navAudit.classList.remove("hidden");
    if (navUsers) navUsers.classList.remove("hidden");
    if (addAccountBtn) addAccountBtn.classList.remove("hidden");
  } else if (role === "account_holder") {
    if (navTransfer) navTransfer.classList.remove("hidden");
    if (navAudit) navAudit.classList.add("hidden");
    if (navUsers) navUsers.classList.add("hidden");
    if (addAccountBtn) addAccountBtn.classList.remove("hidden");
  } else if (role === "auditor") {
    if (navTransfer) navTransfer.classList.add("hidden");
    if (navAudit) navAudit.classList.remove("hidden");
    if (navUsers) navUsers.classList.add("hidden");
    if (addAccountBtn) addAccountBtn.classList.add("hidden"); // Auditor is strictly read-only
  } else {
    // Guest
    if (navTransfer) navTransfer.classList.remove("hidden");
    if (navAudit) navAudit.classList.add("hidden");
    if (navUsers) navUsers.classList.add("hidden");
    if (addAccountBtn) addAccountBtn.classList.remove("hidden");
  }
}

async function handleLogout(showNotification = true) {
  try {
    await fetch("/auth/logout", { method: "POST", credentials: "same-origin" }).catch(() => null);
  } catch (_) {}
  authToken = null;
  currentUser = null;
  localStorage.removeItem("ledgerline_token");
  accounts = [];
  updateAuthUI();
  if (showNotification) showToast("Signed out successfully.");
  setView("accounts");
  renderAccounts();
  renderActivity();
}

// --- Authentication Modal (Login & Registration) ---

function openAuthDialog(defaultTab = "login") {
  let activeTab = defaultTab;

  function renderModalContent() {
    dialogContent.innerHTML = `
      <div class="auth-tabs">
        <button type="button" class="auth-tab ${activeTab === 'login' ? 'active' : ''}" id="tab-btn-login">Sign In</button>
        <button type="button" class="auth-tab ${activeTab === 'register' ? 'active' : ''}" id="tab-btn-register">Create Account</button>
      </div>

      <div id="auth-alert-box"></div>

      ${activeTab === 'login' ? `
        <h2 class="dialog-title">Welcome back</h2>
        <p class="dialog-copy">Sign in with your registered email and password to access the ledger.</p>
        <form id="auth-form" class="form-grid">
          <label class="form-field">
            Email address
            <input name="email" id="auth-email" type="email" required placeholder="admin@gmail.com" autofocus autocomplete="username" />
          </label>
          <label class="form-field">
            Password
            <div class="password-input-wrap">
              <input name="password" id="auth-password" type="password" required placeholder="••••••••" autocomplete="current-password" />
              <button type="button" class="password-toggle-btn" id="toggle-pwd-btn" title="Toggle password visibility">👁</button>
            </div>
          </label>
          <div class="dialog-actions">
            <button class="button button-quiet" type="button" data-dismiss>Cancel</button>
            <button class="button button-primary" type="submit" id="auth-submit-btn">Sign In</button>
          </div>
          <a class="auth-footer-link" id="switch-to-register">Don't have an account? Create one here</a>
        </form>
      ` : `
        <h2 class="dialog-title">Create Account</h2>
        <p class="dialog-copy">Register for LedgerLine access. All public accounts are assigned Account Holder status.</p>
        <form id="auth-form" class="form-grid">
          <label class="form-field">
            Full name
            <input name="full_name" id="reg-name" type="text" placeholder="e.g. Alex Morgan" autocomplete="name" />
          </label>
          <label class="form-field">
            Email address
            <input name="email" id="reg-email" type="email" required placeholder="user@example.com" autocomplete="email" />
          </label>
          <label class="form-field">
            Password (min. 8 characters)
            <div class="password-input-wrap">
              <input name="password" id="reg-password" type="password" minlength="8" required placeholder="••••••••" autocomplete="new-password" />
              <button type="button" class="password-toggle-btn" id="toggle-pwd-btn" title="Toggle password visibility">👁</button>
            </div>
          </label>
          <label class="form-field">
            Confirm password
            <div class="password-input-wrap">
              <input name="confirm_password" id="reg-confirm" type="password" minlength="8" required placeholder="••••••••" autocomplete="new-password" />
              <button type="button" class="password-toggle-btn" id="toggle-confirm-btn" title="Toggle password visibility">👁</button>
            </div>
          </label>
          <div class="dialog-actions">
            <button class="button button-quiet" type="button" data-dismiss>Cancel</button>
            <button class="button button-primary" type="submit" id="auth-submit-btn">Register</button>
          </div>
          <a class="auth-footer-link" id="switch-to-login">Already have an account? Sign in here</a>
        </form>
      `}
    `;

    // Bind Tab Switches
    dialogContent.querySelector("#tab-btn-login")?.addEventListener("click", () => {
      activeTab = "login";
      renderModalContent();
    });
    dialogContent.querySelector("#tab-btn-register")?.addEventListener("click", () => {
      activeTab = "register";
      renderModalContent();
    });
    dialogContent.querySelector("#switch-to-register")?.addEventListener("click", (e) => {
      e.preventDefault();
      activeTab = "register";
      renderModalContent();
    });
    dialogContent.querySelector("#switch-to-login")?.addEventListener("click", (e) => {
      e.preventDefault();
      activeTab = "login";
      renderModalContent();
    });

    // Password show/hide toggle
    const pwdInput = dialogContent.querySelector("#auth-password") || dialogContent.querySelector("#reg-password");
    const pwdToggle = dialogContent.querySelector("#toggle-pwd-btn");
    pwdToggle?.addEventListener("click", () => {
      if (!pwdInput) return;
      const isPwd = pwdInput.type === "password";
      pwdInput.type = isPwd ? "text" : "password";
      pwdToggle.textContent = isPwd ? "🙈" : "👁";
    });

    const confirmInput = dialogContent.querySelector("#reg-confirm");
    const confirmToggle = dialogContent.querySelector("#toggle-confirm-btn");
    confirmToggle?.addEventListener("click", () => {
      if (!confirmInput) return;
      const isPwd = confirmInput.type === "password";
      confirmInput.type = isPwd ? "text" : "password";
      confirmToggle.textContent = isPwd ? "🙈" : "👁";
    });

    // Dismiss button
    dialogContent.querySelector("[data-dismiss]")?.addEventListener("click", () => dialog.close());

    // Submit handler
    const form = dialogContent.querySelector("#auth-form");
    form?.addEventListener("submit", async (e) => {
      e.preventDefault();
      const alertBox = dialogContent.querySelector("#auth-alert-box");
      const submitBtn = dialogContent.querySelector("#auth-submit-btn");
      alertBox.innerHTML = "";

      const formData = new FormData(form);
      const email = String(formData.get("email") || "").trim();
      const password = String(formData.get("password") || "");

      if (activeTab === "register") {
        const confirmPassword = String(formData.get("confirm_password") || "");
        const fullName = String(formData.get("full_name") || "").trim();

        if (password !== confirmPassword) {
          alertBox.innerHTML = `<div class="form-alert error">Passwords do not match. Please verify your password confirmation.</div>`;
          return;
        }

        if (password.length < 8) {
          alertBox.innerHTML = `<div class="form-alert error">Password must be at least 8 characters long.</div>`;
          return;
        }

        submitBtn.disabled = true;
        submitBtn.textContent = "Registering...";

        try {
          await apiRequest("/auth/register", {
            method: "POST",
            body: JSON.stringify({ email, password, full_name: fullName || undefined }),
          });

          alertBox.innerHTML = `<div class="form-alert success">Account created successfully! Switching to sign in...</div>`;
          setTimeout(() => {
            activeTab = "login";
            renderModalContent();
            const emailInput = dialogContent.querySelector("#auth-email");
            if (emailInput) emailInput.value = email;
            const pwdIn = dialogContent.querySelector("#auth-password");
            if (pwdIn) pwdIn.focus();
          }, 1200);
        } catch (err) {
          alertBox.innerHTML = `<div class="form-alert error">${escapeHtml(err.message)}</div>`;
          submitBtn.disabled = false;
          submitBtn.textContent = "Register";
        }
      } else {
        // Login Flow
        submitBtn.disabled = true;
        submitBtn.textContent = "Signing In...";

        try {
          const tokenData = await apiRequest("/auth/login", {
            method: "POST",
            body: JSON.stringify({ email, password }),
          });

          authToken = tokenData.access_token;
          localStorage.setItem("ledgerline_token", authToken);

          // Retrieve authenticated user profile from GET /auth/me
          currentUser = await apiRequest("/auth/me");

          dialog.close();
          updateAuthUI();
          showToast(`Signed in successfully as ${currentUser.email}!`);
          await loadLiveLedger();
        } catch (err) {
          alertBox.innerHTML = `<div class="form-alert error">${escapeHtml(err.message)}</div>`;
          submitBtn.disabled = false;
          submitBtn.textContent = "Sign In";
        }
      }
    });
  }

  renderModalContent();
  dialog.showModal();
}

function handleProfileClick() {
  if (!authToken || !currentUser) {
    openAuthDialog("login");
  } else {
    openDialog(
      "User Session",
      `Currently authenticated as <b>${escapeHtml(currentUser.email)}</b>`,
      `
      <div style="font-size:12px;color:#aab5c2;line-height:1.7;">
        <div><b>User ID:</b> <code>${escapeHtml(currentUser.id)}</code></div>
        <div><b>Assigned Role:</b> <span class="user-table-badge ${currentUser.role}">${escapeHtml(currentUser.role)}</span></div>
        <div style="margin-top:12px;color:#7e8d9e;">Backend authorization is enforced on all ledger queries and money movement operations.</div>
      </div>
      `,
      "Sign Out",
      () => {
        dialog.close();
        handleLogout(true);
      }
    );
  }
}

// --- Live Ledger & Dashboard Data Loading ---

async function loadLiveLedger() {
  try {
    // 1. Check health
    const health = await apiRequest("/health").catch(() => null);
    if (health && health.status === "ok") {
      document.querySelector("#environment-tag").innerHTML = "<i></i> Live DB";
    }

    if (!authToken) {
      document.querySelector(".balanced-pill").innerHTML = "<i>🔒</i> Sign in to view live ledger";
      document.querySelector(".status-detail").textContent = "Authentication required to query live accounts and verify hash chain.";
      renderAccounts();
      renderActivity();
      return;
    }

    // 2. Fetch authenticated profile if missing
    if (!currentUser) {
      currentUser = await apiRequest("/auth/me").catch(() => null);
      updateAuthUI();
    }

    // 3. Cryptographic Hash-Chain Verification (Admin & Auditor)
    const role = currentUser ? (currentUser.role || "").toLowerCase() : "guest";
    if (role === "admin" || role === "auditor") {
      const integrity = await apiRequest("/ledger/verify").catch(() => null);
      if (integrity && integrity.verified) {
        document.querySelector(".balanced-pill").innerHTML = "<i>✓</i> Cryptographic Chain Verified";
        document.querySelector(".status-detail").textContent = `${integrity.total_entries || 0} ledger blocks cryptographically linked & reconciled.`;
      }
    } else if (role === "account_holder") {
      document.querySelector(".balanced-pill").innerHTML = "<i>🔒</i> Customer Account Verified";
      document.querySelector(".status-detail").textContent = "Account balances and immutable statements verified with backend.";
    }

    // 4. Fetch Live Accounts from Backend (Automatically scoped to owner for account_holder, or all for admin/auditor)
    const serverAccounts = await apiRequest("/accounts").catch(() => null);
    if (serverAccounts) {
      accounts = serverAccounts.map((a) => ({
        id: a.id,
        name: a.name,
        owner: a.is_system_account ? "System (Clearing)" : (a.owner_user_id ? (a.owner_user_id === currentUser?.id ? "You (Owner)" : "Customer") : "Unassigned"),
        number: a.id.slice(0, 4),
        bank: a.currency + " Account",
        amount: Math.round(a.balance_minor / 100),
        rawBalance: a.balance_minor,
        currency: a.currency,
        isSystem: a.is_system_account,
        color: a.balance_minor >= 0 ? "green" : "blue",
      }));
      renderAccounts(search.value);
    }

    // 5. Fetch Activity / Statements or Audit Events
    await loadActivityData();
  } catch (err) {
    console.warn("Failed to load live ledger data:", err);
  }
}

async function loadActivityData() {
  const role = currentUser ? (currentUser.role || "").toLowerCase() : "guest";

  if (!authToken) {
    renderActivity();
    return;
  }

  try {
    if (role === "admin" || role === "auditor") {
      // Load real audit events from GET /audit/events
      const events = await apiRequest("/audit/events?limit=25").catch(() => null);
      if (events && events.length > 0) {
        document.querySelector("#activity-heading-title").textContent = "Live Audit Trail";
        document.querySelector("#activity-heading-desc").textContent = "Append-only immutable audit events";
        document.querySelector("#activity-table-head").innerHTML = `
          <tr><th>ACTION</th><th>ACCOUNT</th><th>ACTOR ID</th><th>DATE</th><th>OUTCOME</th><th>DETAILS</th></tr>
        `;
        rows.innerHTML = events.map((ev) => `
          <tr>
            <td><strong>${escapeHtml(ev.action)}</strong></td>
            <td>${ev.account_id ? escapeHtml(ev.account_id.slice(0, 8)) + "..." : "System"}</td>
            <td><code>${ev.actor_user_id ? escapeHtml(ev.actor_user_id.slice(0, 8)) + "..." : "System"}</code></td>
            <td>${ev.created_at ? new Date(ev.created_at).toLocaleString() : "Just now"}</td>
            <td><span class="user-table-badge ${ev.outcome === 'success' ? 'admin' : 'auditor'}">${escapeHtml(ev.outcome)}</span></td>
            <td><span class="hash-pill">${escapeHtml(JSON.stringify(ev.details))}</span></td>
          </tr>
        `).join("");
        document.querySelector("#empty-state").classList.add("hidden");
        return;
      }
    }

    // If account holder or if accounts exist, load entries from the primary account statement
    if (accounts.length > 0) {
      const primaryAcc = accounts[0];
      const statement = await apiRequest(`/statements/${primaryAcc.id}`).catch(() => null);
      if (statement && statement.entries && statement.entries.length > 0) {
        document.querySelector("#activity-heading-title").textContent = `Ledger Activity (${primaryAcc.name})`;
        document.querySelector("#activity-heading-desc").textContent = "Cryptographically chained entries";
        document.querySelector("#activity-table-head").innerHTML = `
          <tr><th>SEQ</th><th>AMOUNT</th><th>BALANCE AFTER</th><th>TIMESTAMP</th><th>HASH CHAIN</th><th>STATUS</th></tr>
        `;
        rows.innerHTML = statement.entries.map((e) => {
          const amt = Math.round(e.amount_minor / 100);
          const bal = Math.round(e.balance_after_minor / 100);
          return `
            <tr>
              <td>#${e.entry_sequence}</td>
              <td class="${amt < 0 ? 'amount-out' : 'amount-in'}">${amt < 0 ? '−' : '+'}₹${money.format(Math.abs(amt))}</td>
              <td>₹${money.format(bal)}</td>
              <td>${e.created_at ? new Date(e.created_at).toLocaleString() : "Recent"}</td>
              <td><span class="hash-pill" title="Hash: ${e.entry_hash}">#${e.entry_hash ? e.entry_hash.slice(0, 10) + '...' : 'Genesis'}</span></td>
              <td><span class="activity-status">Verified</span></td>
            </tr>
          `;
        }).join("");
        document.querySelector("#empty-state").classList.add("hidden");
        return;
      }
    }

    // Empty state
    rows.innerHTML = "";
    document.querySelector("#empty-state").classList.remove("hidden");
  } catch (err) {
    console.warn("Could not load activity:", err);
  }
}

// --- View Rendering & Role Dashboards ---

function renderAccounts(query = "") {
  const term = query.trim().toLowerCase();
  const matches = accounts.filter((account) =>
    `${account.name} ${account.owner} ${account.number} ${account.bank}`.toLowerCase().includes(term)
  );

  grid.innerHTML = matches.map((account, index) => `
    <article class="account-card" style="animation-delay:${index * 65}ms">
      <div class="account-card-top">
        <span class="account-name">${escapeHtml(account.name)}</span>
        <span class="account-status"><i></i> ${account.isSystem ? "System" : "Active"}</span>
      </div>
      <div class="account-amount">₹${money.format(account.amount)} <small>INR</small></div>
      <div class="card-details">
        <div><span class="detail-label">Owner</span><span class="detail-value">${escapeHtml(account.owner)}</span></div>
        <div><span class="detail-label">Account ID</span><span class="detail-value">ACC ···· ${escapeHtml(account.number)}</span></div>
        <div><span class="detail-label">Type</span><span class="detail-value bank">▦ ${escapeHtml(account.bank)}</span></div>
        <div><span class="detail-label">Currency</span><span class="detail-value">INR · Indian rupee</span></div>
      </div>
    </article>
  `).join("");

  document.querySelector("#account-count").textContent = String(matches.length);

  if (activeView === "accounts") {
    const emptyState = document.querySelector("#empty-state");
    if (emptyState && matches.length === 0 && accounts.length === 0 && authToken) {
      grid.innerHTML = `
        <div style="grid-column: 1 / -1; padding: 40px; text-align: center; background: #151c25; border: 1px dashed #2b394a; border-radius: 6px;">
          <h3 style="margin: 0 0 8px; font-family: var(--font-display);">No Accounts Found</h3>
          <p style="color: var(--muted); font-size: 12px; margin-bottom: 16px;">Create your first account on the immutable ledger to begin transacting.</p>
          <button class="button button-primary" onclick="openAccountDialog()">＋ Create Account</button>
        </div>
      `;
    }
  }

  updateTotal();
}

function renderActivity() {
  if (accounts.length === 0 && !authToken) {
    rows.innerHTML = `
      <tr>
        <td colspan="6" style="text-align: center; padding: 24px; color: var(--muted);">
          Sign in to view live ledger transactions and audit events.
        </td>
      </tr>
    `;
  }
}

function updateTotal() {
  const customerAccounts = accounts.filter(a => !a.isSystem);
  const total = (customerAccounts.length > 0 ? customerAccounts : accounts).reduce((sum, account) => sum + account.amount, 0);
  document.querySelector("#system-total").innerHTML = `₹${money.format(total)} <small>INR</small>`;

  const invariantEl = document.querySelector("#footer-invariant-text b");
  if (invariantEl) {
    if (accounts.length > 0) {
      invariantEl.textContent = `Active accounts total ₹${money.format(total)} (System balance reconciled to 0)`;
    } else {
      invariantEl.textContent = "Debits = Credits (Net system sum = 0)";
    }
  }
}

// --- Dynamic Role Views ---

async function renderTransferPanel() {
  const panel = document.querySelector("#transfer-view-panel");
  if (!panel) return;

  const role = currentUser ? (currentUser.role || "").toLowerCase() : "guest";

  if (!authToken) {
    panel.innerHTML = `
      <div class="panel-card">
        <h3>Authentication Required</h3>
        <p>Please sign in to transfer funds between accounts or manage deposits.</p>
        <button class="button button-primary" onclick="openAuthDialog('login')">Sign In</button>
      </div>
    `;
    return;
  }

  if (role === "auditor") {
    panel.innerHTML = `
      <div class="panel-card" style="border-left: 4px solid var(--red);">
        <h3>Access Restricted: Read-Only Role</h3>
        <p>The Auditor role is strictly read-only. Fund movements, transfers, deposits, and withdrawals are prohibited for this role and will be rejected by backend authorization.</p>
        <button class="button button-quiet" onclick="setView('statements')">View Statements Instead</button>
      </div>
    `;
    return;
  }

  const options = accounts.map((acc) => `<option value="${acc.id}">${escapeHtml(acc.name)} (₹${money.format(acc.amount)})</option>`).join("");

  panel.innerHTML = `
    <div style="display: grid; grid-template-columns: repeat(auto-fit, minmax(320px, 1fr)); gap: 20px;">
      <!-- Transfer Card -->
      <div class="panel-card">
        <h3>Execute Atomic Transfer</h3>
        <p>Double-entry transfer with idempotency protection and overdraft prevention.</p>
        <form id="panel-transfer-form" class="form-grid">
          <label class="form-field">From Account<select name="source" required>${options}</select></label>
          <label class="form-field">To Account<select name="destination" required>${options}</select></label>
          <label class="form-field">Amount (INR)<input name="amount" type="number" min="1" step="1" required placeholder="100" /></label>
          <label class="form-field">Idempotency Key<input name="key" required maxlength="80" value="idem-${crypto.randomUUID()}" /></label>
          <button class="button button-primary" type="submit" style="margin-top: 10px;">Submit Transfer</button>
        </form>
      </div>

      <!-- Quick Deposit / Withdrawal Card -->
      <div class="panel-card">
        <h3>Deposit / Withdraw Funds</h3>
        <p>Move funds into or out of an account via system clearing.</p>
        <form id="panel-deposit-form" class="form-grid">
          <label class="form-field">Account<select name="account_id" required>${options}</select></label>
          <label class="form-field">Type
            <select name="action_type" id="deposit-action-type">
              <option value="deposit">Deposit Funds (Inflow)</option>
              <option value="withdrawal">Withdraw Funds (Outflow)</option>
            </select>
          </label>
          <label class="form-field">Amount (INR)<input name="amount" type="number" min="1" step="1" required placeholder="500" /></label>
          <button class="button button-primary" type="submit" style="margin-top: 10px;">Execute Operation</button>
        </form>
      </div>
    </div>
  `;

  // Bind Transfer Form
  panel.querySelector("#panel-transfer-form")?.addEventListener("submit", async (e) => {
    e.preventDefault();
    const form = new FormData(e.currentTarget);
    const source = form.get("source");
    const destination = form.get("destination");
    const amount = Number(form.get("amount"));
    const key = String(form.get("key")).trim();

    if (source === destination) return showToast("Select two different accounts.");
    if (!Number.isSafeInteger(amount) || amount <= 0) return showToast("Enter a positive whole amount.");

    try {
      const res = await apiRequest("/transfers", {
        method: "POST",
        headers: { "Idempotency-Key": key },
        body: JSON.stringify({
          source_account_id: source,
          destination_account_id: destination,
          amount_minor: Math.round(amount * 100),
          description: "Dashboard Transfer",
        }),
      });
      showToast(`Transfer of ₹${money.format(amount)} completed! Tx: ${res.transaction_id.slice(0, 8)}...`);
      await loadLiveLedger();
      renderTransferPanel();
    } catch (err) {
      showToast(`Transfer rejected: ${err.message}`);
    }
  });

  // Bind Deposit/Withdrawal Form
  panel.querySelector("#panel-deposit-form")?.addEventListener("submit", async (e) => {
    e.preventDefault();
    const form = new FormData(e.currentTarget);
    const account_id = form.get("account_id");
    const action_type = form.get("action_type");
    const amount = Number(form.get("amount"));
    const key = `idem-${crypto.randomUUID()}`;

    if (!Number.isSafeInteger(amount) || amount <= 0) return showToast("Enter a positive whole amount.");

    try {
      const endpoint = action_type === "deposit" ? "/deposits" : "/withdrawals";
      const res = await apiRequest(endpoint, {
        method: "POST",
        headers: { "Idempotency-Key": key },
        body: JSON.stringify({
          account_id: account_id,
          amount_minor: Math.round(amount * 100),
          description: `Dashboard ${action_type}`,
        }),
      });
      showToast(`${action_type.toUpperCase()} of ₹${money.format(amount)} successful! New balance: ₹${money.format(res.balance_after / 100)}`);
      await loadLiveLedger();
      renderTransferPanel();
    } catch (err) {
      showToast(`${action_type} failed: ${err.message}`);
    }
  });
}

async function renderStatementsPanel() {
  const panel = document.querySelector("#statements-view-panel");
  if (!panel) return;

  if (!authToken) {
    panel.innerHTML = `
      <div class="panel-card">
        <h3>Authentication Required</h3>
        <p>Please sign in to view account statements and ledger hash-chains.</p>
        <button class="button button-primary" onclick="openAuthDialog('login')">Sign In</button>
      </div>
    `;
    return;
  }

  if (accounts.length === 0) {
    panel.innerHTML = `<div class="panel-card"><p>No accounts available to generate statements.</p></div>`;
    return;
  }

  const options = accounts.map((acc) => `<option value="${acc.id}">${escapeHtml(acc.name)}</option>`).join("");

  panel.innerHTML = `
    <div class="panel-card">
      <div style="display: flex; justify-content: space-between; align-items: center; flex-wrap: wrap; gap: 12px; margin-bottom: 16px;">
        <div>
          <h3>Account Statements &amp; Audit Chain</h3>
          <p style="margin: 0;">Verified ledger blocks with SHA-256 hash-chaining.</p>
        </div>
        <div style="display: flex; align-items: center; gap: 10px;">
          <label style="font-size: 11px; color: var(--muted);">Select Account:</label>
          <select id="statement-account-select" style="height: 36px; background: #111720; color: #fff; border: 1px solid #36414e; border-radius: 4px; padding: 0 10px;">
            ${options}
          </select>
        </div>
      </div>
      <div id="statement-table-container">
        <p style="color: var(--muted); font-size: 12px;">Loading statement records...</p>
      </div>
    </div>
  `;

  const select = panel.querySelector("#statement-account-select");
  async function loadStatementForSelected() {
    const accId = select.value;
    const container = panel.querySelector("#statement-table-container");
    try {
      const stmt = await apiRequest(`/statements/${accId}`);
      if (!stmt.entries || stmt.entries.length === 0) {
        container.innerHTML = `<p style="color: var(--muted); font-size: 12px; padding: 20px 0;">No ledger entries recorded for this account yet.</p>`;
        return;
      }
      container.innerHTML = `
        <div class="table-wrap">
          <table>
            <thead>
              <tr><th>BLOCK #</th><th>TIMESTAMP</th><th>AMOUNT</th><th>BALANCE AFTER</th><th>PREV HASH</th><th>ENTRY HASH</th></tr>
            </thead>
            <tbody>
              ${stmt.entries.map((e) => {
                const amt = Math.round(e.amount_minor / 100);
                const bal = Math.round(e.balance_after_minor / 100);
                return `
                  <tr>
                    <td><strong>#${e.entry_sequence}</strong></td>
                    <td>${e.created_at ? new Date(e.created_at).toLocaleString() : 'Just now'}</td>
                    <td class="${amt < 0 ? 'amount-out' : 'amount-in'}">${amt < 0 ? '−' : '+'}₹${money.format(Math.abs(amt))}</td>
                    <td>₹${money.format(bal)}</td>
                    <td><span class="hash-pill" title="${e.prev_hash}">${e.prev_hash ? e.prev_hash.slice(0, 8) + '...' : 'GENESIS'}</span></td>
                    <td><span class="hash-pill" title="${e.entry_hash}">${e.entry_hash ? e.entry_hash.slice(0, 8) + '...' : '00000000'}</span></td>
                  </tr>
                `;
              }).join("")}
            </tbody>
          </table>
        </div>
      `;
    } catch (err) {
      container.innerHTML = `<p style="color: var(--red); font-size: 12px;">Failed to load statement: ${escapeHtml(err.message)}</p>`;
    }
  }

  select?.addEventListener("change", loadStatementForSelected);
  loadStatementForSelected();
}

async function renderUsersPanel() {
  const panel = document.querySelector("#users-view-panel");
  if (!panel) return;

  const role = currentUser ? (currentUser.role || "").toLowerCase() : "guest";

  if (!authToken || role !== "admin") {
    panel.innerHTML = `
      <div class="panel-card" style="border-left: 4px solid var(--red);">
        <h3>Access Restricted: Administrator Only</h3>
        <p>User management and role authorization controls are restricted to administrators.</p>
      </div>
    `;
    return;
  }

  panel.innerHTML = `
    <div class="panel-card">
      <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 16px;">
        <div>
          <h3>User Management &amp; Role Authorization</h3>
          <p style="margin: 0;">Registered accounts and their backend-assigned role permissions.</p>
        </div>
        <button class="button button-quiet" id="refresh-users-btn">↻ Refresh Users</button>
      </div>
      <div id="users-table-container">
        <p style="color: var(--muted); font-size: 12px;">Loading registered users from backend...</p>
      </div>
    </div>
  `;

  panel.querySelector("#refresh-users-btn")?.addEventListener("click", loadUsersTable);

  async function loadUsersTable() {
    const container = panel.querySelector("#users-table-container");
    try {
      const usersList = await apiRequest("/users");
      if (!usersList || usersList.length === 0) {
        container.innerHTML = `<p style="color: var(--muted);">No users found.</p>`;
        return;
      }
      container.innerHTML = `
        <div class="table-wrap">
          <table>
            <thead>
              <tr><th>USER EMAIL</th><th>ROLE</th><th>STATUS</th><th>USER ID</th><th>REGISTERED</th></tr>
            </thead>
            <tbody>
              ${usersList.map((u) => `
                <tr>
                  <td><strong>${escapeHtml(u.email)}</strong></td>
                  <td><span class="user-table-badge ${u.role}">${escapeHtml(u.role)}</span></td>
                  <td><span class="activity-status">${u.is_active ? 'Active' : 'Disabled'}</span></td>
                  <td><code>${escapeHtml(u.id)}</code></td>
                  <td>${u.created_at ? new Date(u.created_at).toLocaleDateString() : 'N/A'}</td>
                </tr>
              `).join("")}
            </tbody>
          </table>
        </div>
      `;
    } catch (err) {
      container.innerHTML = `<p style="color: var(--red);">Failed to load users: ${escapeHtml(err.message)}</p>`;
    }
  }

  loadUsersTable();
}

// --- Navigation Controller ---

function setView(view) {
  activeView = view;
  const views = {
    accounts: ["Accounts", "Overview of accounts and system integrity", "Accounts", "Active LedgerLine accounts"],
    transfer: ["Transfer & Fund Movement", "Atomic double-entry fund movements and settlements", "Fund Movement", "Double-entry transactions with idempotency protection"],
    statements: ["Statements", "Review account activity and immutable ledger records", "Account Activity", "Cryptographically chained entries"],
    audit: ["Audit Trail", "Review system authorization, security, and integrity events", "System Audit Log", "Append-only immutable events"],
    users: ["User Management", "Role permissions and registered workspace users", "Workspace Users", "Role-Based Access Control policies"],
  };

  const [title, subtitle, section, description] = views[view] || views.accounts;
  document.querySelector("#page-title").textContent = title;
  document.querySelector("#page-subtitle").textContent = subtitle;
  document.querySelector("#section-title").childNodes[0].textContent = `${section} `;
  document.querySelector("#section-description").textContent = description;

  const role = currentUser ? (currentUser.role || "").toLowerCase() : "guest";
  document.querySelector("#add-account").classList.toggle("hidden", view !== "accounts" || role === "auditor");

  // Toggle Visibility of panels
  document.querySelector("#account-grid").classList.toggle("hidden", view !== "accounts");
  document.querySelector("#transfer-view-panel").classList.toggle("hidden", view !== "transfer");
  document.querySelector("#statements-view-panel").classList.toggle("hidden", view !== "statements");
  document.querySelector("#users-view-panel").classList.toggle("hidden", view !== "users");
  document.querySelector("#activity-section").classList.toggle("hidden", !["accounts", "audit"].includes(view));

  document.querySelectorAll(".nav-item").forEach((btn) => btn.classList.toggle("active", btn.dataset.view === view));

  if (view === "transfer") renderTransferPanel();
  if (view === "statements") renderStatementsPanel();
  if (view === "users") renderUsersPanel();
  if (view === "audit") loadActivityData();
}

// --- Account Creation Dialog ---

function openAccountDialog() {
  if (!authToken) {
    openAuthDialog("login");
    return;
  }

  const role = currentUser ? (currentUser.role || "").toLowerCase() : "guest";
  if (role === "auditor") {
    showToast("Auditor role is read-only. Account creation is forbidden.");
    return;
  }

  const isAdmin = role === "admin";

  openDialog(
    "Create New Account",
    "Open an account on the double-entry financial ledger.",
    `
    <label class="form-field">Account name<input name="name" required maxlength="60" placeholder="e.g. Operating account" /></label>
    <label class="form-field">Currency<input name="currency" required maxlength="3" value="INR" /></label>
    ${isAdmin ? `
      <label class="form-field" style="margin-top: 6px;">
        <span style="display:flex;align-items:center;gap:8px;">
          <input type="checkbox" name="is_system" value="true" style="width:16px;height:16px;margin:0;" />
          System Clearing Account (Admin only)
        </span>
      </label>
    ` : ''}
    `,
    "Create Account",
    async (form) => {
      const name = String(form.get("name") || "").trim();
      const currency = String(form.get("currency") || "INR").trim().toUpperCase();
      const isSystem = form.get("is_system") === "true";

      if (!name) return showToast("Enter a valid account name.");

      try {
        const created = await apiRequest("/accounts", {
          method: "POST",
          body: JSON.stringify({
            name,
            currency,
            is_system_account: isSystem,
          }),
        });
        dialog.close();
        showToast(`Account "${created.name}" created successfully on the ledger!`);
        await loadLiveLedger();
      } catch (err) {
        showToast(`Account creation failed: ${err.message}`);
      }
    }
  );
}

function openDialog(title, copy, body, submitLabel, onSubmit) {
  dialogContent.innerHTML = `
    <h2 class="dialog-title">${title}</h2>
    <p class="dialog-copy">${copy}</p>
    <form id="action-form" class="form-grid">
      ${body}
      <div class="dialog-actions">
        <button class="button button-quiet" type="button" data-dismiss>Cancel</button>
        <button class="button button-primary" type="submit">${submitLabel}</button>
      </div>
    </form>
  `;
  dialog.showModal();
  dialog.querySelector("[data-dismiss]")?.addEventListener("click", () => dialog.close());
  dialog.querySelector("#action-form")?.addEventListener("submit", (e) => {
    e.preventDefault();
    onSubmit(new FormData(e.currentTarget));
  });
}

// --- Event Listeners Initialization ---

document.querySelectorAll("[data-view]").forEach((button) => {
  button.addEventListener("click", () => setView(button.dataset.view));
});

document.querySelector("#profile-button")?.addEventListener("click", handleProfileClick);
document.querySelector("#top-avatar")?.addEventListener("click", handleProfileClick);
document.querySelector("#add-account")?.addEventListener("click", openAccountDialog);

document.querySelector("#prompt-signin-btn")?.addEventListener("click", () => openAuthDialog("login"));
document.querySelector("#prompt-register-btn")?.addEventListener("click", () => openAuthDialog("register"));

document.querySelector("#filter-button")?.addEventListener("click", () => {
  search.focus();
  showToast("Type in search to filter accounts.");
});

document.querySelector("#export-button")?.addEventListener("click", async () => {
  if (!authToken) {
    openAuthDialog("login");
    return;
  }
  try {
    const report = await apiRequest("/ledger/reconciliation");
    showToast(`Reconciliation: ${report.is_reconciled ? "Balanced (net sum = 0)" : "Discrepancy detected"}`);
  } catch (err) {
    showToast(`Reconciliation check failed: ${err.message}`);
  }
});

document.querySelector("#refresh-data-button")?.addEventListener("click", async () => {
  await loadLiveLedger();
  showToast("Ledger data refreshed from backend.");
});

search.addEventListener("input", () => {
  renderAccounts(search.value);
});

document.addEventListener("keydown", (event) => {
  if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === "k") {
    event.preventDefault();
    search.focus();
  }
});

// Initial boot
(async function init() {
  updateAuthUI();
  renderAccounts();
  renderActivity();
  await loadLiveLedger();
})();
