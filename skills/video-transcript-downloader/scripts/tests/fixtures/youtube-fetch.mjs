// Replace only network I/O; exercise the real pinned transcript library and CLI.
globalThis.fetch = async (input) => {
  const url = new URL(input);
  if (process.env.VTD_TEST_DIRECT === "fail") return new Response("unavailable", { status: 404 });
  if (url.hostname === "www.youtube.com" && url.pathname === "/watch") {
    return new Response('"INNERTUBE_API_KEY":"fixture"');
  }
  if (url.hostname === "www.youtube.com" && url.pathname === "/youtubei/v1/player") {
    return Response.json({
      captions: { playerCaptionsTracklistRenderer: {
        captionTracks: ["en", "fr"].map((languageCode) => ({
          languageCode, baseUrl: `https://captions.invalid/${languageCode}`,
        })),
      } },
    });
  }
  if (url.hostname === "captions.invalid") {
    const text = process.env.VTD_TEST_DIRECT_TEXT || (url.pathname === "/fr" ? "Bonjour &amp; bienvenue" : "Hello &amp; welcome");
    return new Response(`<transcript><text start="65.5" dur="2">${text}</text><text start="3661" dur="1">[Music]</text></transcript>`);
  }
  throw new Error(`Unexpected test fetch: ${url}`);
};
