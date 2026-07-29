# Room Specifications

One entry per department (room). Source of truth for each field is
`world/districts/definitions/<id>.json` — this table is a human-readable view,
not a duplicate data source.

| Room | Purpose | Visual Theme | Connected Rooms | Future Expansion Hooks |
|---|---|---|---|---|
| AI Department | Strategy deliberation meeting room | glass meeting room, whiteboards, wall screens | CEO Office, Research Lab | sub-department hook for AI Department (Phase W3+) |
| CEO Office | Top-level oversight and final synthesis of engine status | glass corner office, city view, minimal | Command Center, AI Department | sub-department hook for CEO Office (Phase W3+) |
| Command Center | Cross-department communication hub | open-plan command center, wall monitors | CEO Office, Risk Department, Simulation Room, Reception | sub-department hook for Command Center (Phase W3+) |
| Server Room | Data pipeline reflection | server racks, cool blue LED lighting | Market Intelligence Center, Journal Department, Training Room | sub-department hook for Server Room (Phase W3+) |
| Trading Floor | Reflects order execution activity | open trading floor, multi-monitor desks | Risk Department, Garden | sub-department hook for Trading Floor (Phase W3+) |
| Journal Department | Trade history and logs reflection | records room, digital archive wall | Recovery Center, Server Room | sub-department hook for Journal Department (Phase W3+) |
| Market Intelligence Center | External market watch reflection | open research bay, screen wall | Research Lab, Server Room | sub-department hook for Market Intelligence Center (Phase W3+) |
| Garden | Visualizes holdings as living growth | glass atrium, indoor plants, natural light | Trading Floor, Recovery Center | sub-department hook for Garden (Phase W3+) |
| Recovery Center | Reflects drawdown recovery state | calm lounge, soft rising light | Garden, Journal Department | sub-department hook for Recovery Center (Phase W3+) |
| Research Lab | Analysis and prediction reflection | research lab, monitor wall, whiteboards | AI Department, Server Room | sub-department hook for Research Lab (Phase W3+) |
| Risk Department | Defensive systems and risk-state reflection | glass office, risk dashboards, status lights | Trading Floor, Command Center | sub-department hook for Risk Department (Phase W3+) |
| Simulation Room | Scenario/what-if reflection | projection room, holographic displays | Training Room, Command Center | sub-department hook for Simulation Room (Phase W3+) |
| Training Room | Backtesting and drills reflection | training room, screens and whiteboard | Server Room, Simulation Room | sub-department hook for Training Room (Phase W3+) |
| Reception | Entry point and onboarding | modern reception desk, glass entrance | Command Center | sub-department hook for Reception (Phase W3+) |

## Per-room detail

### AI Department

- **id:** `ai-council`
- **Floor:** 3
- **Purpose:** Strategy deliberation meeting room
- **Description:** A glass-walled meeting room where regime and strategy signals are visualized as a whiteboard discussion.
- **Visual theme:** glass meeting room, whiteboards, wall screens
- **Music theme:** focused-discussion
- **Assigned agents:** CHAMELEON
- **Connected rooms:** CEO Office, Research Lab
- **Future expansion hooks:** sub-department hook for AI Department (Phase W3+)

### CEO Office

- **id:** `ceo-tower`
- **Floor:** 3
- **Purpose:** Top-level oversight and final synthesis of engine status
- **Description:** A glass corner office on the top floor overlooking the trading floor; where the highest-level state is reflected.
- **Visual theme:** glass corner office, city view, minimal
- **Music theme:** corporate-ambient-calm
- **Assigned agents:** PRIMUS
- **Connected rooms:** Command Center, AI Department
- **Future expansion hooks:** sub-department hook for CEO Office (Phase W3+)

### Command Center

- **id:** `command-hall`
- **Floor:** 2
- **Purpose:** Cross-department communication hub
- **Description:** An open-plan command center where messages and timing between departments are visualized on wall-mounted monitors.
- **Visual theme:** open-plan command center, wall monitors
- **Music theme:** focused-productivity
- **Assigned agents:** ECHO, CHRONOS
- **Connected rooms:** CEO Office, Risk Department, Simulation Room, Reception
- **Future expansion hooks:** sub-department hook for Command Center (Phase W3+)

### Server Room

- **id:** `data-center`
- **Floor:** 2
- **Purpose:** Data pipeline reflection
- **Description:** Server racks under cool LED lighting, visualizing data flow health.
- **Visual theme:** server racks, cool blue LED lighting
- **Music theme:** server-hum-ambient
- **Assigned agents:** WEBWEAVER
- **Connected rooms:** Market Intelligence Center, Journal Department, Training Room
- **Future expansion hooks:** sub-department hook for Server Room (Phase W3+)

### Trading Floor

- **id:** `execution-forge`
- **Floor:** 2
- **Purpose:** Reflects order execution activity
- **Description:** An open trading floor of multi-monitor desks that light up to represent order fills.
- **Visual theme:** open trading floor, multi-monitor desks
- **Music theme:** energetic-productive
- **Assigned agents:** FORGE
- **Connected rooms:** Risk Department, Garden
- **Future expansion hooks:** sub-department hook for Trading Floor (Phase W3+)

### Journal Department

- **id:** `journal-library`
- **Floor:** 2
- **Purpose:** Trade history and logs reflection
- **Description:** A records room with a digital archive wall, one entry per logged trade or decision.
- **Visual theme:** records room, digital archive wall
- **Music theme:** quiet-archival
- **Assigned agents:** SCRIBE
- **Connected rooms:** Recovery Center, Server Room
- **Future expansion hooks:** sub-department hook for Journal Department (Phase W3+)

### Market Intelligence Center

- **id:** `market-intelligence-center`
- **Floor:** 3
- **Purpose:** External market watch reflection
- **Description:** An open research bay with a wall of screens scanning incoming market data streams.
- **Visual theme:** open research bay, screen wall
- **Music theme:** alert-ambient
- **Assigned agents:** WATCHER
- **Connected rooms:** Research Lab, Server Room
- **Future expansion hooks:** sub-department hook for Market Intelligence Center (Phase W3+)

### Garden

- **id:** `portfolio-garden`
- **Floor:** 1
- **Purpose:** Visualizes holdings as living growth
- **Description:** A glass atrium garden beside the Portfolio Department, where each plant reflects a position and growth mirrors performance.
- **Visual theme:** glass atrium, indoor plants, natural light
- **Music theme:** calm-atrium
- **Assigned agents:** GARDENER
- **Connected rooms:** Trading Floor, Recovery Center
- **Future expansion hooks:** sub-department hook for Garden (Phase W3+)

### Recovery Center

- **id:** `recovery-center`
- **Floor:** 1
- **Purpose:** Reflects drawdown recovery state
- **Description:** A calm wellness lounge that brightens as the engine recovers from drawdown.
- **Visual theme:** calm lounge, soft rising light
- **Music theme:** soft-rising
- **Assigned agents:** PHOENIX
- **Connected rooms:** Garden, Journal Department
- **Future expansion hooks:** sub-department hook for Recovery Center (Phase W3+)

### Research Lab

- **id:** `research-district`
- **Floor:** 3
- **Purpose:** Analysis and prediction reflection
- **Description:** An open research lab with monitor walls showing the engine's research and prediction activity.
- **Visual theme:** research lab, monitor wall, whiteboards
- **Music theme:** curious-analytical
- **Assigned agents:** ORACLE, MANDELBROT
- **Connected rooms:** AI Department, Server Room
- **Future expansion hooks:** sub-department hook for Research Lab (Phase W3+)

### Risk Department

- **id:** `risk-fortress`
- **Floor:** 2
- **Purpose:** Defensive systems and risk-state reflection
- **Description:** A glass risk-management office with dashboard gauges that rise or fall with risk state.
- **Visual theme:** glass office, risk dashboards, status lights
- **Music theme:** focused-vigilant
- **Assigned agents:** BASTION, SENTINEL
- **Connected rooms:** Trading Floor, Command Center
- **Future expansion hooks:** sub-department hook for Risk Department (Phase W3+)

### Simulation Room

- **id:** `simulation-lab`
- **Floor:** 3
- **Purpose:** Scenario/what-if reflection
- **Description:** A digital projection room with shifting holographic displays representing simulated scenarios.
- **Visual theme:** projection room, holographic displays
- **Music theme:** experimental-ambient
- **Assigned agents:** MANDELBROT
- **Connected rooms:** Training Room, Command Center
- **Future expansion hooks:** sub-department hook for Simulation Room (Phase W3+)

### Training Room

- **id:** `training-arena`
- **Floor:** 1
- **Purpose:** Backtesting and drills reflection
- **Description:** A modern training room with screens and a whiteboard where the engine's backtests are reviewed like onboarding sessions.
- **Visual theme:** training room, screens and whiteboard
- **Music theme:** upbeat-focused
- **Assigned agents:** CRUCIBLE
- **Connected rooms:** Server Room, Simulation Room
- **Future expansion hooks:** sub-department hook for Training Room (Phase W3+)

### Reception

- **id:** `world-gateway`
- **Floor:** 1
- **Purpose:** Entry point and onboarding
- **Description:** The front-desk reception where visitors (Krush) arrive and get oriented.
- **Visual theme:** modern reception desk, glass entrance
- **Music theme:** welcoming-corporate
- **Assigned agents:** HERALD
- **Connected rooms:** Command Center
- **Future expansion hooks:** sub-department hook for Reception (Phase W3+)

