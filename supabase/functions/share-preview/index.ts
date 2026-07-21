// ============================================================
// share-preview — Supabase Edge Function
// Génère une page avec des balises Open Graph propres au bien
// demandé (?bien=REF), pour que WhatsApp/Facebook affichent sa
// photo et son prix exacts. Redirige ensuite un vrai visiteur
// vers la vraie vitrine — les robots de partage, eux, ne lisent
// que les balises <meta> et n'exécutent jamais ce script.
// ============================================================
//
// Sauvegarde du code déployé (version 2, récupérée le 21/07/2026).
// Secrets requis : SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY, ALERT_LISTING_URL

const SUPABASE_URL = Deno.env.get("SUPABASE_URL");
const SUPABASE_SERVICE_ROLE_KEY = Deno.env.get("SUPABASE_SERVICE_ROLE_KEY");
// Même secret déjà configuré pour notify-alert-matches : l'URL COMPLÈTE de
// votre page vitrine, ex: https://pabbusiness221.github.io/portefeuille-immobilier/Biens-Immo.html
const SITE_FILE_URL = Deno.env.get("ALERT_LISTING_URL") || "";
// Dossier de base déduit (pour aller chercher og-image.png à côté du fichier).
const SITE_BASE_URL = SITE_FILE_URL.replace(/\/[^/]*$/, "");

function esc(str: string) {
  return String(str ?? "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

const fcfa = (n: number) => Number(n).toLocaleString("fr-FR") + " FCFA";
const surfaceUnit = (type: string) => (type === "Champ agricole" ? "ha" : "m²");

async function fetchProperty(ref: string) {
  const res = await fetch(
    `${SUPABASE_URL}/rest/v1/public_properties?ref=eq.${encodeURIComponent(ref)}&select=id,ref,type,operation,commune,region,surface,price,description`,
    {
      headers: {
        apikey: SUPABASE_SERVICE_ROLE_KEY!,
        Authorization: `Bearer ${SUPABASE_SERVICE_ROLE_KEY}`,
      },
    }
  );
  if (!res.ok) return null;
  const rows = await res.json();
  return rows?.[0] ?? null;
}

async function fetchCoverPhotoUrl(propertyId: string) {
  const res = await fetch(
    `${SUPABASE_URL}/rest/v1/public_property_photos?property_id=eq.${propertyId}&order=is_cover.desc,position.asc&limit=1&select=storage_path`,
    {
      headers: {
        apikey: SUPABASE_SERVICE_ROLE_KEY!,
        Authorization: `Bearer ${SUPABASE_SERVICE_ROLE_KEY}`,
      },
    }
  );
  if (!res.ok) return null;
  const rows = await res.json();
  const path = rows?.[0]?.storage_path;
  return path ? `${SUPABASE_URL}/storage/v1/object/public/property-photos/${path}` : null;
}

function renderRedirectPage(opts: {
  title: string;
  description: string;
  image: string;
  redirectUrl: string;
}) {
  return `<!DOCTYPE html>
<html lang="fr">
<head>
<meta charset="UTF-8">
<meta http-equiv="refresh" content="0;url=${esc(opts.redirectUrl)}">
<title>${esc(opts.title)}</title>
<meta property="og:type" content="website" />
<meta property="og:site_name" content="PAB Immo" />
<meta property="og:locale" content="fr_FR" />
<meta property="og:title" content="${esc(opts.title)}" />
<meta property="og:description" content="${esc(opts.description)}" />
<meta property="og:image" content="${esc(opts.image)}" />
<meta property="og:url" content="${esc(opts.redirectUrl)}" />
<meta name="twitter:card" content="summary_large_image" />
<meta name="twitter:title" content="${esc(opts.title)}" />
<meta name="twitter:description" content="${esc(opts.description)}" />
<meta name="twitter:image" content="${esc(opts.image)}" />
<script>location.replace(${JSON.stringify(opts.redirectUrl)});</script>
</head>
<body>
  <p>Redirection… si rien ne se passe, <a href="${esc(opts.redirectUrl)}">cliquez ici</a>.</p>
</body>
</html>`;
}

Deno.serve(async (req) => {
  const url = new URL(req.url);
  const ref = url.searchParams.get("bien");

  const fallbackImage = SITE_BASE_URL ? `${SITE_BASE_URL}/og-image.png` : "";
  const homeUrl = SITE_FILE_URL || "/";

  if (!SUPABASE_URL || !SUPABASE_SERVICE_ROLE_KEY || !SITE_FILE_URL) {
    // Configuration incomplète : on redirige quand même vers la vitrine
    // générique plutôt que d'afficher une erreur au visiteur.
    return new Response(
      renderRedirectPage({
        title: "PAB Immo",
        description: "Biens à vendre et à louer — Dakar & Thiès.",
        image: fallbackImage,
        redirectUrl: homeUrl,
      }),
      { headers: { "Content-Type": "text/html; charset=utf-8" } }
    );
  }

  if (!ref) {
    return new Response(
      renderRedirectPage({
        title: "PAB Immo — Biens à vendre & à louer, Dakar & Thiès",
        description: "Terrains, maisons, appartements et champs agricoles à Dakar et Thiès.",
        image: fallbackImage,
        redirectUrl: homeUrl,
      }),
      { headers: { "Content-Type": "text/html; charset=utf-8" } }
    );
  }

  const property = await fetchProperty(ref);
  const redirectUrl = `${homeUrl}?bien=${encodeURIComponent(ref)}`;

  if (!property) {
    return new Response(
      renderRedirectPage({
        title: "PAB Immo",
        description: "Ce bien n'est plus disponible — découvrez les autres biens sur PAB Immo.",
        image: fallbackImage,
        redirectUrl: homeUrl,
      }),
      { headers: { "Content-Type": "text/html; charset=utf-8" } }
    );
  }

  const cover = await fetchCoverPhotoUrl(property.id);
  const opLabel = property.operation === "Vente" ? "à vendre" : "à louer";
  const title = `${property.type} ${opLabel} — ${property.commune}, ${property.region}`;
  const priceTxt = `${fcfa(property.price)}${property.operation === "Location" ? "/mois" : ""}`;
  const shortDesc = property.description ? String(property.description).slice(0, 100) : "";
  const description = `${property.surface} ${surfaceUnit(property.type)} · ${priceTxt}${shortDesc ? " — " + shortDesc : ""}`;

  return new Response(
    renderRedirectPage({
      title,
      description,
      image: cover || fallbackImage,
      redirectUrl,
    }),
    { headers: { "Content-Type": "text/html; charset=utf-8" } }
  );
});
