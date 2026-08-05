"use client";
import { useState, useEffect, useRef } from "react";
import { useRouter } from "next/navigation";
import { useAuth } from "@/lib/auth";
import { getStoredAccounts, removeStoredAccount, setActiveAccountId, storeAccount, api, StoredAccount } from "@/lib/api";
import Avatar from "./Avatar";
import Icon from "./Icon";

export default function AccountSwitcher({ open, onClose }: { open: boolean; onClose: () => void }) {
  const { user, refresh } = useAuth();
  const router = useRouter();
  const [accounts, setAccounts] = useState<StoredAccount[]>([]);
  const [switching, setSwitching] = useState<number | null>(null);
  const [loggingOut, setLoggingOut] = useState(false);
  const [switchError, setSwitchError] = useState<string>("");
  const [showAddForm, setShowAddForm] = useState(false);
  const [addUsername, setAddUsername] = useState("");
  const [addPassword, setAddPassword] = useState("");
  const [addShowPw, setAddShowPw] = useState(false);
  const [addError, setAddError] = useState("");
  const [addLoading, setAddLoading] = useState(false);
  const modalRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (open) {
      setAccounts(getStoredAccounts());
      setSwitchError("");
      setShowAddForm(false);
      setAddUsername("");
      setAddPassword("");
      setAddError("");
    }
  }, [open]);

  useEffect(() => {
    if (!open) return;
    const handleClick = (e: MouseEvent) => {
      if (modalRef.current && !modalRef.current.contains(e.target as Node)) onClose();
    };
    const handleKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
      if (e.key === "Backspace") {
        e.preventDefault();
        onClose();
      }
    };
    document.addEventListener("mousedown", handleClick);
    document.addEventListener("keydown", handleKey);
    return () => { document.removeEventListener("mousedown", handleClick); document.removeEventListener("keydown", handleKey); };
  }, [open, onClose]);

  if (!open) return null;

  const handleSwitch = async (account: StoredAccount) => {
    if (user && account.user_id === user.id) { onClose(); return; }
    setSwitching(account.user_id);
    setSwitchError("");
    try {
      await api.switchAccount(account.session_token);
      setActiveAccountId(account.user_id);
      await refresh();
      onClose();
      router.refresh();
    } catch {
      setSwitchError(`${account.display_name}(@${account.username})로 전환할 수 없습니다. 세션이 만료되었을 수 있습니다.`);
    }
    setSwitching(null);
  };

  const handleRemove = async (e: React.MouseEvent, userId: number) => {
    e.stopPropagation();
    removeStoredAccount(userId);
    setAccounts(getStoredAccounts());
    setSwitchError("");
  };

  const handleAddAccount = () => {
    setShowAddForm(true);
    setAddUsername("");
    setAddPassword("");
    setAddError("");
    setAddLoading(false);
  };

  const handleAddLogin = async (e: React.FormEvent) => {
    e.preventDefault();
    setAddLoading(true);
    setAddError("");
    try {
      const result = await api.login(addUsername, addPassword);
      if (result.user && result.session_token) {
        storeAccount({
          user_id: result.user.id,
          username: result.user.username,
          display_name: result.user.display_name,
          avatar: result.user.avatar || "",
          session_token: result.session_token,
        });
        setActiveAccountId(result.user.id);
      }
      await refresh();
      onClose();
      router.refresh();
    } catch (err: unknown) {
      setAddError(err instanceof Error ? err.message : String(err));
    }
    setAddLoading(false);
  };

  const handleLogout = async () => {
    setLoggingOut(true);
    try {
      await api.logout();
      await refresh();
      onClose();
      router.replace("/");
    } finally {
      setLoggingOut(false);
    }
  };

  return (
    <div className="modal-overlay" onClick={onClose}>
      <div className="modal-content account-switcher-modal" ref={modalRef} onClick={(e) => e.stopPropagation()}>
        <div className="modal-header">
          <h3>{showAddForm ? "계정 추가" : "계정 전환"}</h3>
          <button className="modal-close" onClick={onClose}><Icon name="x" /></button>
        </div>
        {switchError && !showAddForm && (
          <div className="account-switcher-error">
            <span>{switchError}</span>
            <button className="account-switcher-error-dismiss" onClick={() => setSwitchError("")}><Icon name="x" size={14} /></button>
          </div>
        )}
        {showAddForm ? (
          <div className="account-switcher-add-form">
            {accounts.length > 0 && (
              <div className="account-switcher-existing">
                <span className="account-switcher-existing-label">저장된 계정</span>
                {accounts.map((a) => (
                  <div key={a.user_id} className="account-switcher-existing-item">
                    <Avatar
                      user={{ username: a.username, display_name: a.display_name, avatar: a.avatar } as any}
                      className="account-switcher-avatar rounded-[8px] flex items-center justify-center text-white font-bold text-lg"
                      style={{ width: 24, height: 24 }}
                    />
                    <span className="account-switcher-existing-name">{a.display_name}</span>
                    <span className="account-switcher-existing-handle">@{a.username}</span>
                  </div>
                ))}
              </div>
            )}
            <form onSubmit={handleAddLogin}>
              <div className="form-group">
                <label>사용자 이름 또는 이메일</label>
                <input value={addUsername} onChange={(e) => setAddUsername(e.target.value)} placeholder="username 또는 email@example.com" required />
              </div>
              <div className="form-group">
                <label>비밀번호</label>
                <div className="pw-input-wrap">
                  <input type={addShowPw ? "text" : "password"} value={addPassword} onChange={(e) => setAddPassword(e.target.value)} placeholder="password" required />
                  <span className="pw-toggle" onClick={() => setAddShowPw(!addShowPw)}><Icon name={addShowPw ? "eye_off" : "eye"} size={16} /></span>
                </div>
              </div>
              {addError && <p className="auth-error">{addError}</p>}
              <button type="submit" disabled={addLoading} className="btn btn-primary" style={{ width: "100%" }}>{addLoading ? "..." : "로그인"}</button>
            </form>
          </div>
        ) : (
        <div className="account-switcher-list">
          {accounts.map((account) => (
            <button
              key={account.user_id}
              className={`account-switcher-item ${user && account.user_id === user.id ? "active" : ""}`}
              onClick={() => handleSwitch(account)}
              disabled={switching !== null}
            >
              <Avatar
                user={{ username: account.username, display_name: account.display_name, avatar: account.avatar } as any}
                className="account-switcher-avatar rounded-[8px] flex items-center justify-center text-white font-bold text-lg"
              />
              <div className="account-switcher-info">
                <span className="account-switcher-name">{account.display_name}</span>
                <span className="account-switcher-handle">@{account.username}</span>
              </div>
              {user && account.user_id === user.id && (
                <span className="account-switcher-active"><Icon name="check" size={16} /></span>
              )}
              {switching === account.user_id && (
                <span className="account-switcher-spinner" />
              )}
              {!(user && account.user_id === user.id) && switching !== account.user_id && (
                <button
                  className="account-switcher-remove"
                  onClick={(e) => handleRemove(e, account.user_id)}
                  title="계정 삭제"
                >
                  <Icon name="x" size={14} />
                </button>
              )}
            </button>
          ))}
          <button className="account-switcher-item account-switcher-add" onClick={handleAddAccount} disabled={switching !== null || loggingOut}>
            <div className="account-switcher-avatar rounded-[8px] flex items-center justify-center" style={{ background: "var(--bg-secondary)" }}>
              <Icon name="plus" size={20} />
            </div>
            <div className="account-switcher-info">
              <span className="account-switcher-name">새 계정 추가</span>
            </div>
          </button>
          <button className="account-switcher-item account-switcher-logout" onClick={handleLogout} disabled={switching !== null || loggingOut}>
            <div className="account-switcher-avatar rounded-[8px] flex items-center justify-center" style={{ background: "var(--bg-secondary)" }}>
              <Icon name="logout" size={20} />
            </div>
            <div className="account-switcher-info">
              <span className="account-switcher-name">{loggingOut ? "로그아웃 중..." : "로그아웃"}</span>
            </div>
          </button>
        </div>
        )}
      </div>
    </div>
  );
}
