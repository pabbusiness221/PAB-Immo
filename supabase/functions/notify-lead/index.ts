// ============================================================
// notify-lead — Supabase Edge Function
// Déclenchée par un Database Webhook sur INSERT pour :
//   contact_messages · appointments · alert_subscriptions
// Envoie un email de notification via Resend.
// ============================================================
//
// Sauvegarde du code déployé (version 6, récupérée le 21/07/2026).
// Secrets requis : RESEND_API_KEY, NOTIFY_EMAIL, NOTIFY_FROM (optionnel),
//                  SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY

const RESEND_API_KEY = Deno.env.get("RESEND_API_KEY");
const NOTIFY_EMAIL = Deno.env.get("NOTIFY_EMAIL");
const SUPABASE_URL = Deno.env.get("SUPABASE_URL");
const SUPABASE_SERVICE_ROLE_KEY = Deno.env.get("SUPABASE_SERVICE_ROLE_KEY");

const fcfa = (n: number | null) =>
  n == null ? null : Number(n).toLocaleString("fr-FR") + " FCFA";

const fmtDate = (iso: string) =>
  new Date(iso).toLocaleString("fr-FR", {
    day: "2-digit",
    month: "short",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });

// Va chercher les infos du bien concerné (ref, type, commune) si property_id existe.
async function fetchProperty(propertyId: string | null) {
  if (!propertyId || !SUPABASE_URL || !SUPABASE_SERVICE_ROLE_KEY) return null;
  try {
    const res = await fetch(
      `${SUPABASE_URL}/rest/v1/properties?id=eq.${propertyId}&select=ref,type,commune,region`,
      {
        headers: {
          apikey: SUPABASE_SERVICE_ROLE_KEY,
          Authorization: `Bearer ${SUPABASE_SERVICE_ROLE_KEY}`,
        },
      }
    );
    if (!res.ok) return null;
    const rows = await res.json();
    return rows?.[0] ?? null;
  } catch {
    return null;
  }
}

function escapeHtml(str: string) {
  return String(str ?? "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;");
}

async function buildEmail(table: string, record: Record<string, any>) {
  const property =
    table === "contact_messages" || table === "appointments"
      ? await fetchProperty(record.property_id)
      : null;

  const propLine = property
    ? `<p style="margin:0 0 12px;color:#5C6470;font-size:13px;">
         Bien concerné : <strong>${escapeHtml(property.ref)}</strong> —
         ${escapeHtml(property.type)}, ${escapeHtml(property.commune)}${property.region ? ", " + escapeHtml(property.region) : ""}
       </p>`
    : table !== "alert_subscriptions"
    ? `<p style="margin:0 0 12px;color:#5C6470;font-size:13px;">Bien concerné : non précisé</p>`
    : "";

  if (table === "contact_messages") {
    return {
      subject: `💬 Nouveau message — ${record.name}`,
      html: `
        <h2 style="margin:0 0 4px;">Nouveau message de contact</h2>
        ${propLine}
        <p style="margin:0 0 4px;"><strong>Nom :</strong> ${escapeHtml(record.name)}</p>
        <p style="margin:0 0 4px;"><strong>Contact :</strong> ${escapeHtml(record.contact)}</p>
        <p style="margin:12px 0;padding:12px;background:#F1EFE7;border-radius:10px;">${escapeHtml(record.message)}</p>
        <p style="margin:16px 0 0;color:#8B9199;font-size:12px;">Reçu le ${fmtDate(record.created_at)}</p>
      `,
    };
  }

  if (table === "appointments") {
    return {
      subject: `📅 Nouvelle demande de RDV — ${record.name}`,
      html: `
        <h2 style="margin:0 0 4px;">Nouvelle demande de rendez-vous</h2>
        ${propLine}
        <p style="margin:0 0 4px;"><strong>Nom :</strong> ${escapeHtml(record.name)}</p>
        <p style="margin:0 0 4px;"><strong>Contact :</strong> ${escapeHtml(record.contact)}</p>
        <p style="margin:0 0 4px;"><strong>Date souhaitée :</strong> ${new Date(record.preferred_date).toLocaleDateString("fr-FR")}${record.preferred_time ? " — " + escapeHtml(record.preferred_time) : ""}</p>
        ${record.message ? `<p style="margin:12px 0;padding:12px;background:#F1EFE7;border-radius:10px;">${escapeHtml(record.message)}</p>` : ""}
        <p style="margin:16px 0 0;color:#8B9199;font-size:12px;">Reçu le ${fmtDate(record.created_at)}</p>
      `,
    };
  }

  if (table === "alert_subscriptions") {
    const criteria = [record.type, record.operation, record.region].filter(Boolean).join(" · ") || "Tous types";
    const budget = fcfa(record.budget_max);
    return {
      subject: `🔔 Nouvelle inscription aux alertes — ${record.email}`,
      html: `
        <h2 style="margin:0 0 4px;">Nouvelle inscription aux alertes</h2>
        <p style="margin:0 0 4px;"><strong>Email :</strong> ${escapeHtml(record.email)}</p>
        <p style="margin:0 0 4px;"><strong>Critères :</strong> ${escapeHtml(criteria)}</p>
        ${budget ? `<p style="margin:0 0 4px;"><strong>Budget max :</strong> ${escapeHtml(budget)}</p>` : ""}
        <p style="margin:16px 0 0;color:#8B9199;font-size:12px;">Reçu le ${fmtDate(record.created_at)}</p>
      `,
    };
  }

  return null;
}

Deno.serve(async (req) => {
  if (req.method !== "POST") {
    return new Response("Method not allowed", { status: 405 });
  }

  if (!RESEND_API_KEY || !NOTIFY_EMAIL) {
    console.error("RESEND_API_KEY ou NOTIFY_EMAIL manquant dans les secrets.");
    return new Response("Missing configuration", { status: 500 });
  }

  let payload: any;
  try {
    payload = await req.json();
  } catch {
    return new Response("Invalid JSON", { status: 400 });
  }

  const { type, table, record } = payload ?? {};

  // On ne traite que les insertions sur les 3 tables concernées.
  if (type !== "INSERT" || !record) {
    return new Response("Ignored", { status: 200 });
  }
  if (!["contact_messages", "appointments", "alert_subscriptions"].includes(table)) {
    return new Response("Ignored table", { status: 200 });
  }

  const email = await buildEmail(table, record);
  if (!email) {
    return new Response("Nothing to send", { status: 200 });
  }

  const resendRes = await fetch("https://api.resend.com/emails", {
    method: "POST",
    headers: {
      Authorization: `Bearer ${RESEND_API_KEY}`,
      "Content-Type": "application/json",
    },
    body: JSON.stringify({
      from: Deno.env.get("NOTIFY_FROM") || "PAB Immo <onboarding@resend.dev>",
      to: [NOTIFY_EMAIL],
      subject: email.subject,
      html: `<div style="font-family:sans-serif;color:#161B22;max-width:480px;">${email.html}</div>`,
    }),
  });

  if (!resendRes.ok) {
    const errText = await resendRes.text();
    console.error("Échec envoi Resend:", errText);
    return new Response("Resend error: " + errText, { status: 502 });
  }

  return new Response("OK", { status: 200 });
});
