// Every text the customer can see lives here, so the page can be translated
// later by swapping this one object. `dir` will become "rtl" for Arabic.
const STRINGS = {
  botName: "Zelli",
  locale: "en",
  dir: "ltr",

  title: "MoroccoTech Support",
  greeting: "Hi! I'm Zelli, how can I help you today?",
  newChat: "New chat",
  you: "You",
  typing: "Typing",

  inputPlaceholder: "Write your message…",
  inputLabel: "Your message",
  send: "Send",
  counter: (n, max) => `${n} / ${max}`,

  errorText: "Sorry, I couldn't reach our server. Please check your connection and try again.",
  retry: "Retry",

  handoffLine: "Zelli couldn't answer this one",
  handoffTitle: "No live agent in this chat",
  handoffBody:
    "Nobody from our team is following this chat right now, so you won't get a reply here. You can ask something else or start a new chat.",

  botTagline: "MoroccoTech assistant",

  quickTitle: "Quick questions",
  quickQuestions: [
    "Is the Mechanical Keyboard K1 in stock?",
    "How long does delivery to Tangier take?",
    "Can I pay cash on delivery?",
    "What is your return policy?",
  ],

  // Copied from data/knowledge_base (shipping, returns, payments, FAQ). Keep them in sync.
  factsTitle: "Good to know",
  facts: [
    { value: "500 MAD", label: "Free shipping above" },
    { value: "1–2 days", label: "Delivery to Casablanca and Rabat" },
    { value: "14 days", label: "To return an unused product" },
    { value: "Cash or card", label: "Cash on delivery all over Morocco, or pay by card" },
  ],
};

export default STRINGS;
