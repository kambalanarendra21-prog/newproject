(() => {
  const log = document.getElementById("job-log");
  if (!log) return;
  const jobId = log.dataset.jobId;
  let status = log.dataset.status;
  if (!jobId || status !== "running") return;

  const tick = async () => {
    try {
      const res = await fetch(`/api/jobs/${jobId}`);
      if (!res.ok) return;
      const data = await res.json();
      const text = (data.logs || [])
        .map((line) => `[${line.level}] ${line.message}`)
        .join("\n");
      log.textContent = text + (text ? "\n" : "");
      log.scrollTop = log.scrollHeight;
      status = data.status;
      if (status === "running") {
        setTimeout(tick, 1500);
      } else {
        window.location.reload();
      }
    } catch (_) {
      setTimeout(tick, 2500);
    }
  };
  setTimeout(tick, 1200);
})();
