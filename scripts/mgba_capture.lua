-- mGBA Lua script: advance N frames and save a screenshot.
--
-- Usage: Load this script in mGBA (Tools -> Scripting -> Load),
-- then load a ROM. The script auto-captures after FRAMES frames.
--
-- Configure via environment or edit these constants:
local FRAMES = tonumber(os.getenv("MGBA_FRAMES") or "120")
local OUTPUT = os.getenv("MGBA_OUTPUT") or "mgba-capture.png"

local frame_count = 0
local captured = false

callbacks:add("frame", function()
    frame_count = frame_count + 1
    if frame_count >= FRAMES and not captured then
        emu:screenshot(OUTPUT)
        console:log("Captured frame " .. frame_count .. " to " .. OUTPUT)
        captured = true
    end
end)

console:log("mgba-capture: will capture at frame " .. FRAMES .. " to " .. OUTPUT)
