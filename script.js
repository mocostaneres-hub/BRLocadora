const bookingForm = document.querySelector("#bookingForm");
const formNote = document.querySelector("#formNote");

bookingForm?.addEventListener("submit", (event) => {
  event.preventDefault();

  const formData = new FormData(bookingForm);
  const name = formData.get("nome")?.toString().trim();
  const email = formData.get("email")?.toString().trim();
  const service = formData.get("servico")?.toString().trim();
  const date = formData.get("data")?.toString().trim();
  const message = formData.get("mensagem")?.toString().trim();

  const request = [
    `Olá, sou ${name || "um cliente"}.`,
    email ? `Meu e-mail é ${email}.` : "",
    service ? `Tenho interesse em: ${service}.` : "",
    date ? `Data desejada: ${date}.` : "",
    message ? `Mensagem: ${message}` : "",
  ]
    .filter(Boolean)
    .join(" ");

  navigator.clipboard
    ?.writeText(request)
    .then(() => {
      formNote.textContent =
        "Mensagem preparada e copiada. Agora basta colar no WhatsApp ou enviar pelo canal de atendimento.";
    })
    .catch(() => {
      formNote.textContent = request;
    });
});
