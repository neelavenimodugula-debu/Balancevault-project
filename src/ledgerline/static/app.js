const accounts = [
  { name: "Savings Account", owner: "Riya Sharma", number: "7812", bank: "HDFC · Savings", amount: 45000, color: "green" },
  { name: "Operating Account", owner: "LedgerLine Inc.", number: "2245", bank: "ICICI · Operating", amount: 30000, color: "blue" },
  { name: "Escrow Account", owner: "Neel Patel", number: "9091", bank: "SBI · Escrow", amount: 25000, color: "amber" },
];

const activity = [
  { kind: "Transfer", detail: "Internal movement", account: "Operating Account", actor: "Alex Morgan", date: "Nov 06, 2026 · 14:32", amount: -5200 },
  { kind: "Deposit", detail: "Opening funding", account: "Savings Account", actor: "Alex Morgan", date: "Nov 06, 2026 · 13:18", amount: 15000 },
  { kind: "Withdrawal", detail: "Vendor settlement", account: "Escrow Account", actor: "Neel Patel", date: "Nov 05, 2026 · 17:46", amount: -3200 },
];

const money = new Intl.NumberFormat("en-IN", { maximumFractionDigits: 0 });
const grid = document.querySelector("#account-grid");
const rows = document.querySelector("#activity-rows");
const search = document.querySelector("#global-search");
const dialog = document.querySelector("#action-dialog");
const dialogContent = document.querySelector("#dialog-content");
let activeView = "accounts";
let activeRole = "Administrator";
let toastTimer;

function renderAccounts(query = "") {
  const term = query.trim().toLowerCase();
  const matches = accounts.filter((account) => `${account.name} ${account.owner} ${account.number} ${account.bank}`.toLowerCase().includes(term));
  grid.innerHTML = matches.map((account, index) => `
    <article class="account-card" style="animation-delay:${index * 65}ms">
      <div class="account-card-top"><span class="account-name">${escapeHtml(account.name)}</span><span class="account-status"><i></i> Active</span></div>
      <div class="account-amount">₹${money.format(account.amount)} <small>INR</small></div>
      <div class="card-details">
        <div><span class="detail-label">Owner</span><span class="detail-value">${escapeHtml(account.owner)}</span></div>
        <div><span class="detail-label">Account number</span><span class="detail-value">ACC ···· ${escapeHtml(account.number)}</span></div>
        <div><span class="detail-label">Institution</span><span class="detail-value bank">▦ ${escapeHtml(account.bank)}</span></div>
        <div><span class="detail-label">Currency</span><span class="detail-value">INR · Indian rupee</span></div>
      </div>
    </article>`).join("");
  document.querySelector("#account-count").textContent = String(matches.length);
  if (activeView === "accounts") document.querySelector("#empty-state").classList.toggle("hidden", matches.length > 0);
  updateTotal();
}

function renderActivity(query = "") {
  const term = query.trim().toLowerCase();
  const matches = activity.filter((item) => `${item.kind} ${item.detail} ${item.account} ${item.actor}`.toLowerCase().includes(term));
  rows.innerHTML = matches.map((item) => `
    <tr>
      <td><span class="activity-kind"><span class="activity-icon ${item.amount < 0 ? "outgoing" : ""}">${item.amount < 0 ? "↗" : "↙"}</span><span>${escapeHtml(item.kind)}<br><span style="color:#7f8b99;font-size:9px;font-weight:400">${escapeHtml(item.detail)}</span></span></span></td>
      <td>${escapeHtml(item.account)}</td><td>${escapeHtml(item.actor)}</td><td>${escapeHtml(item.date)}</td>
      <td class="${item.amount < 0 ? "amount-out" : "amount-in"}">${item.amount < 0 ? "−" : "+"}₹${money.format(Math.abs(item.amount))}</td><td><span class="activity-status">Sample</span></td>
    </tr>`).join("");
  if (activeView !== "accounts") document.querySelector("#empty-state").classList.toggle("hidden", matches.length > 0);
}

function updateTotal() {
  const total = accounts.reduce((sum, account) => sum + account.amount, 0);
  document.querySelector("#system-total").innerHTML = `₹${money.format(total)} <small>INR</small>`;
  document.querySelector(".invariant-footer b").textContent = accounts.map((account) => `₹${money.format(account.amount)}`).join(" + ") + ` = ₹${money.format(total)}`;
}

function escapeHtml(value) {
  return String(value).replace(/[&<>"']/g, (character) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[character]);
}

function showToast(message) {
  const toast = document.querySelector("#toast");
  toast.textContent = message;
  toast.classList.add("visible");
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => toast.classList.remove("visible"), 3000);
}

function setView(view) {
  activeView = view;
  const views = {
    accounts: ["Accounts", "Overview of accounts and system integrity", "Accounts", "All balances shown are sample data"],
    transfer: ["Transfer", "Prepare an internal movement between accounts", "Transfer preview", "Sandbox only · no money will move"],
    statements: ["Statements", "Review sample account activity", "Account activity", "Sample events · not a bank statement"],
    audit: ["Audit log", "Review sample authorization and integrity events", "Recent audit events", "Illustrative records only"],
    users: ["Users & roles", "Preview role permissions for this workspace", "Workspace roles", "Role selector is for interface preview only"],
  };
  const [title, subtitle, section, description] = views[view] || views.accounts;
  document.querySelector("#page-title").textContent = title;
  document.querySelector("#page-subtitle").textContent = subtitle;
  document.querySelector("#section-title").childNodes[0].textContent = `${section} `;
  document.querySelector("#section-description").textContent = description;
  document.querySelector("#add-account").classList.toggle("hidden", view !== "accounts" || activeRole === "Auditor");
  document.querySelector("#account-grid").classList.toggle("hidden", !["accounts", "users"].includes(view));
  document.querySelector(".activity-section").classList.toggle("hidden", !["accounts", "statements", "audit"].includes(view));
  document.querySelector(".integrity-banner").classList.toggle("hidden", view === "users");
  document.querySelectorAll(".nav-item").forEach((button) => button.classList.toggle("active", button.dataset.view === view));
  if (view === "transfer") openTransferDialog();
  if (view === "users") renderRoleView();
  else renderAccounts(search.value);
  renderActivity(search.value);
}

function renderRoleView() {
  grid.innerHTML = [
    ["Administrator", "Manage users and accounts; authorize explicitly attributed funding and adjustments.", "Write access", "#3fc985"],
    ["Account Holder", "View owned accounts; request allowed deposits, withdrawals, and transfers.", "Own accounts only", "#79a9ff"],
    ["Auditor", "Read accounts, statements, and audit events. Cannot move money.", "Read only", "#e4a654"],
  ].map(([name, description, access, color]) => `<article class="account-card role-card"><div class="account-card-top"><span class="account-name">${name}</span><span class="account-status" style="color:${color};border-color:${color}55">${access}</span></div><p style="margin-top:20px;color:#aab5c2;font-size:11px;line-height:1.6">${description}</p></article>`).join("");
}

function openDialog(title, copy, body, submitLabel, onSubmit) {
  dialogContent.innerHTML = `<h2 class="dialog-title">${title}</h2><p class="dialog-copy">${copy}</p><form id="action-form" class="form-grid">${body}<div class="form-hint">Sandbox preview only. This form is not connected to the ledger and will not move real funds.</div><div class="dialog-actions"><button class="button button-quiet" type="button" data-dismiss>Cancel</button><button class="button button-primary" type="submit">${submitLabel}</button></div></form>`;
  dialog.showModal();
  dialog.querySelector("[data-dismiss]").addEventListener("click", () => dialog.close());
  dialog.querySelector("#action-form").addEventListener("submit", (event) => {
    event.preventDefault();
    onSubmit(new FormData(event.currentTarget));
  });
}

function openAccountDialog() {
  if (activeRole === "Auditor") return showToast("Auditor role is read-only.");
  openDialog("Add account", "Create a sample account card for this browser preview.", `
    <label class="form-field">Account name<input name="name" required maxlength="60" placeholder="e.g. Payroll account" /></label>
    <label class="form-field">Owner<input name="owner" required maxlength="60" placeholder="Person or organization" /></label>
    <label class="form-field">Starting balance (INR)<input name="amount" type="number" min="0" step="1" required placeholder="0" /></label>`, "Add sample account", (form) => {
    const name = String(form.get("name")).trim();
    const owner = String(form.get("owner")).trim();
    const amount = Number(form.get("amount"));
    if (!name || !owner || !Number.isSafeInteger(amount) || amount < 0) return showToast("Enter valid account details and a whole-rupee balance.");
    accounts.push({ name, owner, number: String(Math.floor(1000 + Math.random() * 9000)), bank: "LedgerLine · Preview", amount, color: "green" });
    dialog.close();
    renderAccounts(search.value);
    showToast("Sample account added in this browser preview only.");
  });
}

function openTransferDialog() {
  if (activeRole === "Auditor") {
    showToast("Auditor role is read-only. Transfer preview is unavailable.");
    setView("accounts");
    return;
  }
  const options = accounts.map((account, index) => `<option value="${index}">${escapeHtml(account.name)} · ₹${money.format(account.amount)}</option>`).join("");
  openDialog("New transfer", "Select accounts and an amount to preview the form. Submitting will not change balances.", `
    <label class="form-field">From account<select name="source" required>${options}</select></label>
    <label class="form-field">To account<select name="destination" required>${options}</select></label>
    <label class="form-field">Amount (INR)<input name="amount" type="number" min="1" step="1" required placeholder="0" /></label>
    <label class="form-field">Idempotency key<input name="key" required maxlength="80" value="preview-${crypto.randomUUID()}" /></label>`, "Preview transfer", (form) => {
    const source = Number(form.get("source"));
    const destination = Number(form.get("destination"));
    const amount = Number(form.get("amount"));
    if (source === destination) return showToast("Choose two different accounts.");
    if (!Number.isSafeInteger(amount) || amount <= 0) return showToast("Enter a positive whole-rupee amount.");
    if (amount > accounts[source].amount) return showToast("Sample source balance is insufficient.");
    dialog.close();
    showToast("Preview validated only. No transfer or ledger entry was created.");
  });
}

document.querySelectorAll("[data-view]").forEach((button) => button.addEventListener("click", () => setView(button.dataset.view)));
document.querySelectorAll(".role-chip").forEach((button) => button.addEventListener("click", () => {
  activeRole = button.dataset.role;
  document.querySelectorAll(".role-chip").forEach((chip) => chip.classList.toggle("selected", chip === button));
  document.querySelector(".profile-copy small").textContent = activeRole;
  showToast(`Preview role changed to ${activeRole}; server authorization is not connected.`);
  setView(activeView);
}));
document.querySelector("#add-account").addEventListener("click", openAccountDialog);
document.querySelector("#filter-button").addEventListener("click", () => {
  search.focus();
  showToast("Type in search to filter accounts and activity.");
});
document.querySelector("#export-button").addEventListener("click", () => showToast("Export is not available in the preview workspace."));
document.querySelector("#profile-button").addEventListener("click", () => showToast(`Signed in as a sample ${activeRole.toLowerCase()}.`));
search.addEventListener("input", () => { renderAccounts(search.value); renderActivity(search.value); });
document.addEventListener("keydown", (event) => {
  if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === "k") { event.preventDefault(); search.focus(); }
});

renderAccounts();
renderActivity();