// Pacific Classics — admin data: decrypts data/admin.enc (gzip + AES-256-GCM, PBKDF2-SHA256 "user:password")
window.PCAdmin = (() => {
  const b64 = s => Uint8Array.from(atob(s), c => c.charCodeAt(0));
  async function open(user, password) {
    const env = await fetch("data/admin.enc", { cache: "no-store" }).then(r => { if (!r.ok) throw new Error("no bundle"); return r.json(); });
    const base = await crypto.subtle.importKey("raw", new TextEncoder().encode(`${user}:${password}`), "PBKDF2", false, ["deriveKey"]);
    const key = await crypto.subtle.deriveKey({ name: "PBKDF2", hash: "SHA-256", salt: b64(env.salt), iterations: env.iter },
      base, { name: "AES-GCM", length: 256 }, false, ["decrypt"]);
    const plain = await crypto.subtle.decrypt({ name: "AES-GCM", iv: b64(env.iv) }, key, b64(env.data));   // throws on wrong credentials
    const stream = new Blob([plain]).stream().pipeThrough(new DecompressionStream("gzip"));
    return JSON.parse(await new Response(stream).text());
  }
  return { open };
})();
