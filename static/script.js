Shery.mouseFollower();
Shery.makeMagnet(".magnet");

gsap.to(".fleftelm", {
  scrollTrigger: {
    trigger: "#fimages",
    pin: true,
    start: "top top",
    end: "bottom bottom",
    endTrigger: ".last",
    scrub: 1,
  },
  y: "-300%",
  ease: Power1,
});

let sections = document.querySelectorAll(".fleftelm");
Shery.imageEffect(".images", {
  style: 4,
  config: { onMouse: { value: 1 } },
  slideStyle: (setScroll) => {
    sections.forEach(function (section, index) {
      ScrollTrigger.create({
        trigger: section,
        start: "top top",
        scrub: 1,
        onUpdate: function (prog) {
          setScroll(prog.progress + index);
        },
      });
    });
  },
});


const { createClient } = supabase;

const _supabseUrl = "https://aefchhzedxoyrikhvisr.supabase.co";
const _supabaseKey = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6ImFlZmNoaHplZHhveXJpa2h2aXNyIiwicm9sZSI6ImFub24iLCJpYXQiOjE3NjM5NTU1NjcsImV4cCI6MjA3OTUzMTU2N30.9dT2U6XNO-A6Y756MJiPHCarwDzMHi-K5ivfUvbFzkA";
const client = createClient(_supabseUrl, _supabaseKey);

async function fetchUniquePatients() {
  try {
    const { data, error } = await client
      .from("user_chat_media")
      .select("phone_num")
      .neq("user_message", "NULL")
      .not("user_message", "is", null);

    if (error) {
      console.error("Error fetching patient data:", error);
      return;
    }

    const uniquePatients = new Set(data.map(item => item.phone_num));
    const uniqueCount = uniquePatients.size;

    console.log("Unique patients count:", uniqueCount);
    updatePatientCount(uniqueCount);
  } catch (error) {
    console.error("Unexpected error:", error);
  }
}

function updatePatientCount(count) {
  const allCounters = document.querySelectorAll(".counter-wrapper");

  if (allCounters[0]) {
    const counterElement = allCounters[0].querySelector(".counter");
    counterElement.innerText = count;
    counterElement.setAttribute("data-count", count);
  }
}

async function fetchHospitalCount() {
  try {
    const { count, error } = await client
      .from("hospitals")
      .select("*", { count: "exact", head: true });

    if (error) {
      console.error("Error fetching hospital count:", error);
      return;
    }

    console.log("Total hospitals:", count);
    updateHospitalCount(count);
  } catch (error) {
    console.error("Unexpected error:", error);
  }
}

function updateHospitalCount(totalNumber) {
  const allCounters = document.querySelectorAll(".counter-wrapper");

  if (allCounters[1]) {
    const counterElement = allCounters[1].querySelector(".counter");

    counterElement.innerText = totalNumber;

    counterElement.setAttribute("data-count", totalNumber);
  }
}

async function fetchSolvedQueries() {
  try {
    const { data, error } = await client.rpc("count_queries_solved");

    if (error) {
      console.error("Error fetching solved queries:", error);
      return;
    }

    console.log("Queries Solved (Streaks > 3):", data);
    updateSolvedCount(data);
  } catch (error) {
    console.error("Unexpected Error:", error);
  }
}

function updateSolvedCount(count) {
  const allCounters = document.querySelectorAll(".counter-wrapper");

  if (allCounters[2]) {
    const counterElement = allCounters[2].querySelector(".counter");

    counterElement.innerText = count;
    counterElement.setAttribute("data-count", count);
  }
}

const timeline = document.querySelector('.timeline');
const timelineContainers = document.querySelectorAll('.timeline-container');

const observer = new IntersectionObserver(entries => {
  entries.forEach(entry => {
    if (entry.isIntersecting) {
      entry.target.classList.add('show');
      timeline.classList.add('show-line');
      timeline.classList.remove('hide-line');
      observer.unobserve(entry.target);
    }
  });
}, {
  threshold: 0.8
});

timelineContainers.forEach(container => {
  observer.observe(container);
});

window.addEventListener('scroll', () => {
  const timelineRect = timeline.getBoundingClientRect();
  const top = timelineRect.top;
  const bottom = timelineRect.bottom;

  if (top > window.innerHeight / 2 || bottom < window.innerHeight / 2) {
    timeline.classList.remove('show-line');
    timeline.classList.add('hide-line');
  } else {
    timeline.classList.add('show-line');
    timeline.classList.remove('hide-line');
  }
});

const screenshots = document.querySelectorAll('.screen-overlay');

screenshots.forEach(img => {
  img.addEventListener('click', function (e) {
    // Stop the click from bubbling up (optional, good practice)
    e.stopPropagation();

    // Toggle the 'zoomed' class
    this.classList.toggle('zoomed');
  });
});

document.addEventListener('click', function (e) {
  if (!e.target.classList.contains('screen-overlay')) {
    screenshots.forEach(img => img.classList.remove('zoomed'));
  }
});

// Select elements
const chatBtn = document.getElementById('chatBtn');
const popup = document.getElementById('qrPopup');
const closeIcon = document.querySelector('.close-icon');

// 1. Open Popup
chatBtn.addEventListener('click', () => {
    popup.classList.add('show');
});

// 2. Close Popup (Clicking X)
closeIcon.addEventListener('click', () => {
    popup.classList.remove('show');
});

// 3. Close Popup (Clicking outside the card)
popup.addEventListener('click', (e) => {
    // If the user clicks the dark background (popup-overlay) directly
    if (e.target === popup) {
        popup.classList.remove('show');
    }
});


fetchUniquePatients();
fetchHospitalCount();
fetchSolvedQueries();