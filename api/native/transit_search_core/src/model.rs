use std::cmp::Ordering;

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct StopTimeRow {
    pub stop_index: u32,
    pub arrival_minute: Option<u32>,
    pub departure_minute: Option<u32>,
}

#[derive(Clone, Copy, Debug, Eq, Ord, PartialEq, PartialOrd)]
pub struct Departure {
    pub minute: u32,
    pub trip_index: u32,
    pub row_index: u32,
}

#[derive(Clone, Debug, Eq, Ord, PartialEq, PartialOrd)]
pub struct Leg {
    pub trip_index: u32,
    pub route_index: u32,
    pub from_stop_index: u32,
    pub to_stop_index: u32,
    pub departure_minute: u32,
    pub arrival_minute: u32,
    pub stop_indices: Vec<u32>,
}

pub type PathKey = Vec<Leg>;

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum Preference {
    Fastest,
    FewestTransfers,
}

impl Preference {
    pub fn parse(value: &str) -> Result<Self, String> {
        match value {
            "fastest" => Ok(Self::Fastest),
            "fewest_transfers" => Ok(Self::FewestTransfers),
            _ => Err(format!("unsupported search preference: {value}")),
        }
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct QueueEntry {
    pub primary: u32,
    pub secondary: u32,
    pub path_key: PathKey,
    pub serial: u64,
    pub stop_index: u32,
    pub rides: u8,
}

impl Ord for QueueEntry {
    fn cmp(&self, other: &Self) -> Ordering {
        (
            self.primary,
            self.secondary,
            &self.path_key,
            self.serial,
            self.stop_index,
            self.rides,
        )
            .cmp(&(
                other.primary,
                other.secondary,
                &other.path_key,
                other.serial,
                other.stop_index,
                other.rides,
            ))
    }
}

impl PartialOrd for QueueEntry {
    fn partial_cmp(&self, other: &Self) -> Option<Ordering> {
        Some(self.cmp(other))
    }
}

#[derive(Clone, Debug)]
pub struct Endpoint {
    pub stop_index: u32,
    pub walk_minutes: u32,
}

#[derive(Clone, Copy, Debug)]
pub struct Limits {
    pub max_visited_states: u64,
    pub max_queue_size: usize,
    pub max_generated_labels: u64,
    pub time_limit_seconds: f64,
}

#[derive(Clone, Debug)]
pub struct Itinerary {
    pub departure_minute: u32,
    pub arrival_minute: u32,
    pub legs: Vec<Leg>,
}

#[derive(Clone, Debug)]
pub struct PairResult {
    pub origin_index: u32,
    pub destination_index: u32,
    pub itinerary: Itinerary,
}

#[derive(Clone, Debug)]
pub struct Diagnostics {
    pub visited_states: u64,
    pub queue_peak: usize,
    pub generated_labels: u64,
    pub origin_searches: u32,
    pub termination_reason: String,
    pub elapsed_nanoseconds: u64,
}

#[derive(Clone, Debug)]
pub struct SearchResult {
    pub pairs: Vec<PairResult>,
    pub diagnostics: Diagnostics,
}
