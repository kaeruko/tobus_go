use crate::model::{Departure, StopTimeRow};

#[derive(Clone, Debug)]
pub struct TransitIndex {
    pub stop_count: usize,
    pub service_count: usize,
    pub trip_route_indices: Vec<u32>,
    pub trip_service_indices: Vec<u32>,
    pub trip_rows: Vec<Vec<StopTimeRow>>,
    pub departures_by_stop: Vec<Vec<Departure>>,
}

impl TransitIndex {
    #[allow(clippy::too_many_arguments)]
    pub fn new(
        stop_count: usize,
        route_count: usize,
        service_count: usize,
        trip_route_indices: Vec<u32>,
        trip_service_indices: Vec<u32>,
        trip_offsets: Vec<u32>,
        trip_stop_indices: Vec<u32>,
        arrival_minutes: Vec<i32>,
        departure_minutes: Vec<i32>,
    ) -> Result<Self, String> {
        let trip_count = trip_route_indices.len();
        if trip_service_indices.len() != trip_count {
            return Err("trip route/service arrays have different lengths".to_string());
        }
        if trip_offsets.len() != trip_count + 1 || trip_offsets.first() != Some(&0) {
            return Err(
                "trip_offsets must start at zero and have trip_count + 1 entries".to_string(),
            );
        }
        let row_count = trip_stop_indices.len();
        if arrival_minutes.len() != row_count || departure_minutes.len() != row_count {
            return Err("stop-time arrays have different lengths".to_string());
        }
        if trip_offsets.last().copied().map(|value| value as usize) != Some(row_count) {
            return Err("trip_offsets does not end at the stop-time array length".to_string());
        }

        let mut trip_rows = Vec::with_capacity(trip_count);
        let mut departures_by_stop = vec![Vec::new(); stop_count];
        for trip_index in 0..trip_count {
            let route_index = trip_route_indices[trip_index] as usize;
            let service_index = trip_service_indices[trip_index] as usize;
            if route_index >= route_count {
                return Err(format!("trip {trip_index} has an invalid route index"));
            }
            if service_index >= service_count {
                return Err(format!("trip {trip_index} has an invalid service index"));
            }
            let start = trip_offsets[trip_index] as usize;
            let end = trip_offsets[trip_index + 1] as usize;
            if end <= start || end > row_count {
                return Err(format!("trip {trip_index} has invalid stop-time offsets"));
            }
            let mut rows = Vec::with_capacity(end - start);
            let mut previous_clock = None;
            for (row_index, flat_index) in (start..end).enumerate() {
                let stop_index = trip_stop_indices[flat_index];
                if stop_index as usize >= stop_count {
                    return Err(format!("trip {trip_index} has an invalid stop index"));
                }
                let arrival_minute = optional_minute(arrival_minutes[flat_index])?;
                let departure_minute = optional_minute(departure_minutes[flat_index])?;
                if arrival_minute.is_none() && departure_minute.is_none() {
                    return Err(format!("trip {trip_index} has an empty stop time"));
                }
                let event_clock = departure_minute.or(arrival_minute);
                if let (Some(previous), Some(current)) = (previous_clock, event_clock) {
                    if current < previous {
                        return Err(format!("trip {trip_index} times go backwards"));
                    }
                }
                if event_clock.is_some() {
                    previous_clock = event_clock;
                }
                if let Some(minute) = departure_minute {
                    departures_by_stop[stop_index as usize].push(Departure {
                        minute,
                        trip_index: trip_index as u32,
                        row_index: row_index as u32,
                    });
                }
                rows.push(StopTimeRow {
                    stop_index,
                    arrival_minute,
                    departure_minute,
                });
            }
            trip_rows.push(rows);
        }
        for departures in &mut departures_by_stop {
            departures.sort_unstable();
        }

        Ok(Self {
            stop_count,
            service_count,
            trip_route_indices,
            trip_service_indices,
            trip_rows,
            departures_by_stop,
        })
    }
}

fn optional_minute(value: i32) -> Result<Option<u32>, String> {
    match value {
        -1 => Ok(None),
        value if value >= 0 => Ok(Some(value as u32)),
        _ => Err(format!("invalid negative service minute: {value}")),
    }
}
