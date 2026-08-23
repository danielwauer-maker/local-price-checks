import "./lib/api-client";
import "./pwa";

import { StartClient } from "@tanstack/react-start/client";
import { hydrateRoot } from "react-dom/client";

hydrateRoot(document, <StartClient />);
