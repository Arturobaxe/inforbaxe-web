(() => {
  "use strict";

  async function resolverCita(id, estado) {
    const texto = estado === "completada"
      ? "¿Confirmas que el cliente ha asistido?"
      : "¿Confirmas que el cliente no ha asistido?";
    if (!confirm(texto)) return;
    try {
      const endpoint = estado === "completada" ? "completar" : "no-asistio";
      const response = await fetch(`/api/citas/${encodeURIComponent(String(id))}/${endpoint}`, {
        method: "POST"
      });
      if (!response.ok) throw new Error("No se pudo actualizar la cita");
      location.reload();
    } catch (error) {
      alert(error.message || "Error al actualizar la cita");
    }
  }

  document.addEventListener("click", (event) => {
    const button = event.target instanceof Element
      ? event.target.closest("[data-cita-action]")
      : null;
    if (!button) return;
    if (button.dataset.citaAction === "resolver") {
      resolverCita(button.dataset.citaId, button.dataset.citaEstado);
    } else if (button.dataset.citaAction === "delete" &&
               typeof window.confirmDelete === "function") {
      window.confirmDelete(button.dataset.url, button.dataset.msg);
    }
  });

  // Calendario mensual compacto con agenda del día seleccionado.
  const calendar = document.getElementById("appointments-calendar");
  if (calendar) {
    const monthLabel = document.getElementById("calendar-month-label");
    const daysGrid = document.getElementById("calendar-days");
    const agendaTitle = document.getElementById("calendar-agenda-title");
    const agendaSubtitle = document.getElementById("calendar-agenda-subtitle");
    const agendaList = document.getElementById("calendar-agenda-list");
    const newAppointment = document.getElementById("calendar-new-appointment");
    const navButtons = calendar.querySelectorAll("[data-calendar-nav]");
    const statusInfo = {
      pendiente: {label: "Pendiente", className: "pending"},
      completada: {label: "Completada", className: "completed"},
      no_asistio: {label: "No asistió", className: "no-show"},
      cancelada: {label: "Cancelada", className: "cancelled"},
      otro: {label: "Otro estado", className: "other"}
    };
    const parseLocalDate = (value) => {
      const match = /^([0-9]{4})-([0-9]{2})-([0-9]{2})$/.exec(value || "");
      return match ? new Date(Number(match[1]), Number(match[2]) - 1, Number(match[3])) : null;
    };
    const dateKey = (date) => [
      date.getFullYear(),
      String(date.getMonth() + 1).padStart(2, "0"),
      String(date.getDate()).padStart(2, "0")
    ].join("-");
    const monthKey = (date) => date.getFullYear() * 12 + date.getMonth();
    const formatMonth = new Intl.DateTimeFormat("es-ES", {month: "long", year: "numeric"});
    const formatDay = new Intl.DateTimeFormat("es-ES", {
      weekday: "long", day: "numeric", month: "long"
    });
    let appointments = [];
    try {
      const parsed = JSON.parse(calendar.dataset.appointments || "[]");
      if (Array.isArray(parsed)) appointments = parsed.filter((item) =>
        item && Number.isSafeInteger(Number(item.id)) &&
        parseLocalDate(item.fecha) && statusInfo[item.estado]
      );
    } catch (_) {
      appointments = [];
    }
    appointments.sort((a, b) =>
      a.fecha.localeCompare(b.fecha) || String(a.hora).localeCompare(String(b.hora))
    );
    const appointmentsByDate = new Map();
    appointments.forEach((item) => {
      if (!appointmentsByDate.has(item.fecha)) appointmentsByDate.set(item.fecha, []);
      appointmentsByDate.get(item.fecha).push(item);
    });

    const today = parseLocalDate(calendar.dataset.today) || new Date();
    today.setHours(0, 0, 0, 0);
    const minMonth = parseLocalDate((calendar.dataset.minMonth || "") + "-01");
    const maxMonth = parseLocalDate((calendar.dataset.maxMonth || "") + "-01");
    let visibleMonth = new Date(today.getFullYear(), today.getMonth(), 1);

    function addEventRow(item, includeDate) {
      const row = document.createElement("a");
      row.className = "calendar-event";
      row.href = "/citas/" + encodeURIComponent(String(item.id)) + "/editar";

      const time = document.createElement("span");
      time.className = "calendar-event-time";
      time.textContent = item.hora || "—";

      const details = document.createElement("span");
      details.className = "calendar-event-details";
      const client = document.createElement("strong");
      client.textContent = item.cliente || "Cliente";
      const status = document.createElement("small");
      const info = statusInfo[item.estado] || statusInfo.otro;
      status.className = "calendar-status " + info.className;
      status.textContent = info.label;
      details.append(client, status);
      row.append(time, details);

      if (includeDate) {
        const eventDate = document.createElement("small");
        eventDate.className = "calendar-event-date";
        const date = parseLocalDate(item.fecha);
        eventDate.textContent = date ? formatDay.format(date) : item.fecha;
        row.appendChild(eventDate);
      }
      return row;
    }

    function renderUpcoming() {
      agendaTitle.textContent = "Próximas citas";
      agendaSubtitle.textContent = "Selecciona un día para ver su agenda";
      agendaList.replaceChildren();
      const todayKey = dateKey(today);
      const upcoming = appointments.filter((item) => item.fecha >= todayKey).slice(0, 5);
      if (!upcoming.length) {
        const empty = document.createElement("p");
        empty.className = "calendar-empty";
        empty.textContent = "No tienes citas próximas registradas.";
        agendaList.appendChild(empty);
      } else {
        upcoming.forEach((item) => agendaList.appendChild(addEventRow(item, true)));
      }
      newAppointment.href = "/citas/nueva";
    }

    function renderSelectedDay(selectedDate) {
      const date = parseLocalDate(selectedDate);
      if (!date) return;
      agendaTitle.textContent = "Citas del día";
      agendaSubtitle.textContent = formatDay.format(date);
      agendaList.replaceChildren();
      const dayAppointments = appointmentsByDate.get(selectedDate) || [];
      if (!dayAppointments.length) {
        const empty = document.createElement("p");
        empty.className = "calendar-empty";
        empty.textContent = "No hay citas para este día.";
        agendaList.appendChild(empty);
      } else {
        dayAppointments.forEach((item) => agendaList.appendChild(addEventRow(item, false)));
      }
      newAppointment.href = "/citas/nueva?fecha=" + encodeURIComponent(selectedDate);
    }

    function renderCalendar(selectedDate) {
      monthLabel.textContent = formatMonth.format(visibleMonth);
      daysGrid.replaceChildren();
      const year = visibleMonth.getFullYear();
      const month = visibleMonth.getMonth();
      const firstDay = new Date(year, month, 1);
      const mondayOffset = (firstDay.getDay() + 6) % 7;
      const totalDays = Math.ceil((mondayOffset + new Date(year, month + 1, 0).getDate()) / 7) * 7;
      for (let offset = 0; offset < totalDays; offset += 1) {
        const date = new Date(year, month, 1 - mondayOffset + offset);
        const key = dateKey(date);
        const dayAppointments = appointmentsByDate.get(key) || [];
        const button = document.createElement("button");
        button.type = "button";
        button.className = "calendar-day";
        if (date.getMonth() !== month) button.classList.add("outside-month");
        if (key === dateKey(today)) button.classList.add("is-today");
        if (key === selectedDate) button.classList.add("is-selected");
        button.setAttribute("aria-pressed", key === selectedDate ? "true" : "false");
        button.setAttribute("aria-label", formatDay.format(date) + ", " + dayAppointments.length + " citas");
        const number = document.createElement("span");
        number.className = "calendar-day-number";
        number.textContent = String(date.getDate());
        button.appendChild(number);

        if (dayAppointments.length) {
          const dots = document.createElement("span");
          dots.className = "calendar-day-dots";
          dots.setAttribute("aria-hidden", "true");
          dayAppointments.slice(0, 4).forEach((item) => {
            const dot = document.createElement("i");
            dot.className = "calendar-dot " + (statusInfo[item.estado] || statusInfo.otro).className;
            dots.appendChild(dot);
          });
          if (dayAppointments.length > 4) {
            const more = document.createElement("small");
            more.textContent = "+" + (dayAppointments.length - 4);
            dots.appendChild(more);
          }
          button.appendChild(dots);
        } else {
          const spacer = document.createElement("span");
          spacer.className = "calendar-day-dots";
          button.appendChild(spacer);
        }
        button.addEventListener("click", () => {
          const nextMonth = new Date(date.getFullYear(), date.getMonth(), 1);
          if (minMonth && monthKey(nextMonth) < monthKey(minMonth)) return;
          if (maxMonth && monthKey(nextMonth) > monthKey(maxMonth)) return;
          visibleMonth = nextMonth;
          renderCalendar(key);
          renderSelectedDay(key);
        });
        daysGrid.appendChild(button);
      }

      navButtons.forEach((button) => {
        const action = button.dataset.calendarNav;
        if (action === "today") return;
        const offset = action === "previous" ? -1 : 1;
        const candidate = new Date(year, month + offset, 1);
        button.disabled = Boolean(
          (minMonth && monthKey(candidate) < monthKey(minMonth)) ||
          (maxMonth && monthKey(candidate) > monthKey(maxMonth))
        );
      });
    }

    navButtons.forEach((button) => button.addEventListener("click", () => {
      const action = button.dataset.calendarNav;
      if (action === "today") {
        visibleMonth = new Date(today.getFullYear(), today.getMonth(), 1);
        renderCalendar(dateKey(today));
        renderUpcoming();
        return;
      }
      const offset = action === "previous" ? -1 : 1;
      const candidate = new Date(visibleMonth.getFullYear(), visibleMonth.getMonth() + offset, 1);
      if ((minMonth && monthKey(candidate) < monthKey(minMonth)) ||
          (maxMonth && monthKey(candidate) > monthKey(maxMonth))) return;
      visibleMonth = candidate;
      renderCalendar("");
      renderUpcoming();
    }));

    renderCalendar("");
    renderUpcoming();
  }

  // Swipe para borrar en móvil.
  if ("ontouchstart" in window) {
    document.querySelectorAll('tbody tr[id^="cita-row-"]').forEach((row) => {
      let startX = 0;
      row.addEventListener("touchstart", (event) => {
        startX = event.touches[0].clientX;
      }, {passive: true});
      row.addEventListener("touchend", (event) => {
        const diff = startX - event.changedTouches[0].clientX;
        if (diff > 80) row.querySelector(".delete-cita")?.click();
      }, {passive: true});
    });
  }
})();
