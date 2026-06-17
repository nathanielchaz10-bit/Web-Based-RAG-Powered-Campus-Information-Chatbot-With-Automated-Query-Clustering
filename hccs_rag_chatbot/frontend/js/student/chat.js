document.addEventListener("DOMContentLoaded", () => {
    const chatInput = document.getElementById("chat-input");
    const sendBtn = document.getElementById("send-btn");

    // Automatically focus the input box so you can start typing immediately
    chatInput.focus();

    function handleSend() {
        const text = chatInput.value.trim();
        if (!text) return;

        console.log("User sent:", text);

        // Clear the input
        chatInput.value = "";

        // TODO: In the next step, we will use JS to move the input box
        // to the bottom of the screen and reveal the chat history div!
    }

    // Trigger send on button click
    sendBtn.addEventListener("click", handleSend);

    // Trigger send on Enter key
    chatInput.addEventListener("keypress", (e) => {
        if (e.key === "Enter") {
            e.preventDefault();
            handleSend();
        }
    });
});